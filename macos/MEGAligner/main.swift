import Cocoa

private let appName = "MEGAligner"
private let defaultModel = "sentence-transformers/LaBSE"
private let defaultUVVersion = "0.11.15"
private let bundledProjectDirectory = "MEGAligner"

private struct TmxPreviewRow {
    let source: String
    let target: String
}

private final class TmxPreviewParser: NSObject, XMLParserDelegate {
    private(set) var rows: [TmxPreviewRow] = []
    private(set) var parseError: Error?
    private var insideTranslationUnit = false
    private var insideSegment = false
    private var currentSegments: [String] = []
    private var currentSegmentText = ""

    func parser(
        _ parser: XMLParser,
        didStartElement elementName: String,
        namespaceURI: String?,
        qualifiedName qName: String?,
        attributes attributeDict: [String: String] = [:]
    ) {
        switch elementName {
        case "tu":
            insideTranslationUnit = true
            currentSegments = []
        case "seg" where insideTranslationUnit:
            insideSegment = true
            currentSegmentText = ""
        default:
            break
        }
    }

    func parser(_ parser: XMLParser, foundCharacters string: String) {
        if insideSegment {
            currentSegmentText += string
        }
    }

    func parser(_ parser: XMLParser, foundCDATA CDATABlock: Data) {
        guard insideSegment, let text = String(data: CDATABlock, encoding: .utf8) else {
            return
        }
        currentSegmentText += text
    }

    func parser(
        _ parser: XMLParser,
        didEndElement elementName: String,
        namespaceURI: String?,
        qualifiedName qName: String?
    ) {
        switch elementName {
        case "seg" where insideSegment:
            currentSegments.append(normalizedSegment(currentSegmentText))
            insideSegment = false
            currentSegmentText = ""
        case "tu" where insideTranslationUnit:
            if currentSegments.count >= 2 {
                rows.append(TmxPreviewRow(source: currentSegments[0], target: currentSegments[1]))
            }
            insideTranslationUnit = false
            currentSegments = []
        default:
            break
        }
    }

    func parser(_ parser: XMLParser, parseErrorOccurred parseError: Error) {
        self.parseError = parseError
    }

    private func normalizedSegment(_ value: String) -> String {
        value.replacingOccurrences(
            of: #"\s+"#,
            with: " ",
            options: .regularExpression
        )
        .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

private func isProjectRoot(_ url: URL) -> Bool {
    let fileManager = FileManager.default
    let bootstrap = url.appendingPathComponent("scripts/bootstrap_uv.sh").path
    let package = url.appendingPathComponent("docx_bitext_aligner").path
    return fileManager.fileExists(atPath: bootstrap) && fileManager.fileExists(atPath: package)
}

private func findProjectRoot() -> URL? {
    let fileManager = FileManager.default
    if let override = ProcessInfo.processInfo.environment["MEGALIGNER_ROOT"] {
        let url = URL(fileURLWithPath: override).standardizedFileURL
        if isProjectRoot(url) {
            return url
        }
    }

    if let resourceURL = Bundle.main.resourceURL {
        let bundledProject = resourceURL.appendingPathComponent(bundledProjectDirectory).standardizedFileURL
        if isProjectRoot(bundledProject) {
            return bundledProject
        }
    }

    var candidates: [URL] = [
        Bundle.main.bundleURL.deletingLastPathComponent(),
        URL(fileURLWithPath: fileManager.currentDirectoryPath).standardizedFileURL
    ]

    if let resourceURL = Bundle.main.resourceURL {
        candidates.append(resourceURL)
    }

    var seen = Set<String>()
    for candidate in candidates {
        var url = candidate.standardizedFileURL
        while true {
            let path = url.path
            if !seen.contains(path) {
                seen.insert(path)
                if isProjectRoot(url) {
                    return url
                }
            }

            let parent = url.deletingLastPathComponent()
            if parent.path == url.path {
                break
            }
            url = parent
        }
    }

    return nil
}

private func applicationSupportDirectory() -> URL {
    let fileManager = FileManager.default
    if let url = try? fileManager.url(
        for: .applicationSupportDirectory,
        in: .userDomainMask,
        appropriateFor: nil,
        create: true
    ) {
        return url.appendingPathComponent(appName, isDirectory: true)
    }
    return URL(fileURLWithPath: NSHomeDirectory())
        .appendingPathComponent("Library/Application Support/\(appName)", isDirectory: true)
}

private func shellQuote(_ value: String) -> String {
    "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
}

private func makeSymbol(_ name: String, fallback: String) -> NSImage? {
    if #available(macOS 11.0, *) {
        return NSImage(systemSymbolName: name, accessibilityDescription: fallback)
    }
    return nil
}

private func accentColor() -> NSColor {
    NSColor(calibratedRed: 0.05, green: 0.42, blue: 0.74, alpha: 1)
}

private enum RunMode {
    case preview
    case align

    var title: String {
        switch self {
        case .preview:
            return "Previewing pairs"
        case .align:
            return "Aligning documents"
        }
    }
}

final class MainWindowController: NSWindowController, NSTableViewDataSource, NSTableViewDelegate {
    private let projectRoot: URL
    private var inputURL: URL?
    private var outputURL: URL?
    private var previewSucceeded = false
    private var currentProcess: Process?
    private var outputBuffer = ""
    private var runStartedAt: Date?
    private var progressStageStartedAt: Date?
    private var progressStageName: String?
    private var completedSelectionKey: String?
    private var tmxRows: [TmxPreviewRow] = []
    private var detailsExpanded = false

    private let inputField = NSTextField()
    private let outputField = NSTextField()
    private let devicePopup = NSPopUpButton()
    private let previewButton = NSButton(title: "Preview", target: nil, action: nil)
    private let alignButton = NSButton(title: "Align", target: nil, action: nil)
    private let cancelButton = NSButton(title: "Cancel", target: nil, action: nil)
    private let revealButton = NSButton(title: "Reveal Output", target: nil, action: nil)
    private let progressIndicator = NSProgressIndicator()
    private let statusLabel = NSTextField(labelWithString: "Choose a DOCX folder and TMX output file.")
    private let statusRow = NSStackView()
    private let tmxSummaryLabel = NSTextField(labelWithString: "TMX Preview appears here after alignment.")
    private let tmxTableView = NSTableView()
    private let tmxScrollView = NSScrollView()
    private let detailsButton = NSButton(title: "Show Details", target: nil, action: nil)
    private let logScrollView = NSScrollView()
    private let logView = NSTextView(frame: NSRect(x: 0, y: 0, width: 760, height: 320))

    init(projectRoot: URL) {
        self.projectRoot = projectRoot

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 900, height: 760),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = appName
        window.minSize = NSSize(width: 780, height: 640)
        super.init(window: window)
        buildInterface()
        updateControls()
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    private func buildInterface() {
        guard let contentView = window?.contentView else {
            return
        }
        contentView.wantsLayer = true
        contentView.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor

        let rootStack = NSStackView()
        rootStack.orientation = .vertical
        rootStack.alignment = .width
        rootStack.spacing = 16
        rootStack.detachesHiddenViews = true
        rootStack.translatesAutoresizingMaskIntoConstraints = false
        contentView.addSubview(rootStack)

        NSLayoutConstraint.activate([
            rootStack.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 24),
            rootStack.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -24),
            rootStack.topAnchor.constraint(equalTo: contentView.topAnchor, constant: 22),
            rootStack.bottomAnchor.constraint(equalTo: contentView.bottomAnchor, constant: -22)
        ])

        let header = NSStackView()
        header.orientation = .horizontal
        header.alignment = .centerY
        header.spacing = 14

        let iconView = NSImageView()
        iconView.image = NSImage(named: "MEGAligner") ?? NSApp.applicationIconImage
        iconView.imageScaling = .scaleProportionallyUpOrDown
        iconView.toolTip = appName
        iconView.addGestureRecognizer(NSClickGestureRecognizer(target: self, action: #selector(showHeartEasterEgg(_:))))
        iconView.widthAnchor.constraint(equalToConstant: 58).isActive = true
        iconView.heightAnchor.constraint(equalToConstant: 58).isActive = true

        let titleStack = NSStackView()
        titleStack.orientation = .vertical
        titleStack.alignment = .leading
        titleStack.spacing = 3

        let title = NSTextField(labelWithString: appName)
        title.font = .systemFont(ofSize: 28, weight: .semibold)
        title.setContentHuggingPriority(.required, for: .vertical)

        let subtitle = NSTextField(labelWithString: "Create a TMX translation memory from paired DOCX files.")
        subtitle.font = .systemFont(ofSize: 14)
        subtitle.textColor = .secondaryLabelColor
        subtitle.setContentHuggingPriority(.required, for: .vertical)

        titleStack.addArrangedSubview(title)
        titleStack.addArrangedSubview(subtitle)
        header.addArrangedSubview(iconView)
        header.addArrangedSubview(titleStack)
        rootStack.addArrangedSubview(header)

        configurePathField(inputField, placeholder: "No folder selected")
        configurePathField(outputField, placeholder: "No output file selected")

        let inputButton = NSButton(title: "Choose Folder", target: self, action: #selector(chooseInputFolder))
        inputButton.image = makeSymbol("folder", fallback: "Folder")
        inputButton.imagePosition = .imageLeading

        let outputButton = NSButton(title: "Save As", target: self, action: #selector(chooseOutputFile))
        outputButton.image = makeSymbol("square.and.arrow.down", fallback: "Save")
        outputButton.imagePosition = .imageLeading

        let setupStack = NSStackView()
        setupStack.orientation = .vertical
        setupStack.alignment = .width
        setupStack.spacing = 12

        let setupTitle = NSTextField(labelWithString: "Workspace")
        setupTitle.font = .systemFont(ofSize: 13, weight: .semibold)
        setupTitle.textColor = accentColor()
        setupStack.addArrangedSubview(setupTitle)
        setupStack.addArrangedSubview(makePathRow(label: "DOCX Folder", field: inputField, button: inputButton))
        setupStack.addArrangedSubview(makePathRow(label: "Output TMX", field: outputField, button: outputButton))

        devicePopup.addItems(withTitles: ["Auto", "Apple Silicon", "CPU"])
        devicePopup.toolTip = "Embedding device"

        let deviceLabel = NSTextField(labelWithString: "Device")
        deviceLabel.alignment = .right
        deviceLabel.widthAnchor.constraint(equalToConstant: 92).isActive = true

        let optionsRow = NSStackView(views: [deviceLabel, devicePopup])
        optionsRow.orientation = .horizontal
        optionsRow.alignment = .centerY
        optionsRow.spacing = 10
        setupStack.addArrangedSubview(optionsRow)
        rootStack.addArrangedSubview(setupStack)

        previewButton.target = self
        previewButton.action = #selector(runPreview)
        previewButton.image = makeSymbol("doc.text.magnifyingglass", fallback: "Preview")
        previewButton.imagePosition = .imageLeading

        alignButton.target = self
        alignButton.action = #selector(runAlignment)
        alignButton.keyEquivalent = "\r"
        alignButton.bezelStyle = .rounded
        alignButton.contentTintColor = accentColor()
        alignButton.image = makeSymbol("play.fill", fallback: "Align")
        alignButton.imagePosition = .imageLeading

        cancelButton.target = self
        cancelButton.action = #selector(cancelRun)
        cancelButton.image = makeSymbol("stop.fill", fallback: "Cancel")
        cancelButton.imagePosition = .imageLeading

        revealButton.target = self
        revealButton.action = #selector(revealOutput)
        revealButton.image = makeSymbol("arrow.up.forward.app", fallback: "Reveal")
        revealButton.imagePosition = .imageLeading

        let buttonRow = NSStackView(views: [previewButton, alignButton, cancelButton, revealButton])
        buttonRow.orientation = .horizontal
        buttonRow.alignment = .centerY
        buttonRow.spacing = 10
        rootStack.addArrangedSubview(buttonRow)

        progressIndicator.style = .bar
        progressIndicator.controlSize = .regular
        progressIndicator.minValue = 0
        progressIndicator.maxValue = 1
        progressIndicator.doubleValue = 0
        progressIndicator.isIndeterminate = false
        progressIndicator.isDisplayedWhenStopped = true
        progressIndicator.heightAnchor.constraint(equalToConstant: 14).isActive = true

        statusLabel.lineBreakMode = .byWordWrapping
        statusLabel.maximumNumberOfLines = 2
        statusLabel.setContentHuggingPriority(.defaultLow, for: .vertical)
        statusLabel.setContentCompressionResistancePriority(.required, for: .vertical)

        statusRow.addArrangedSubview(progressIndicator)
        statusRow.addArrangedSubview(statusLabel)
        statusRow.orientation = .vertical
        statusRow.alignment = .width
        statusRow.spacing = 6
        rootStack.addArrangedSubview(statusRow)
        statusRow.widthAnchor.constraint(equalTo: rootStack.widthAnchor).isActive = true

        tmxSummaryLabel.font = .systemFont(ofSize: 13, weight: .semibold)
        tmxSummaryLabel.textColor = .secondaryLabelColor
        rootStack.addArrangedSubview(tmxSummaryLabel)

        configurePreviewTable()
        tmxScrollView.borderType = .lineBorder
        tmxScrollView.hasVerticalScroller = true
        tmxScrollView.hasHorizontalScroller = false
        tmxScrollView.autohidesScrollers = true
        tmxScrollView.documentView = tmxTableView
        tmxScrollView.translatesAutoresizingMaskIntoConstraints = false
        tmxScrollView.heightAnchor.constraint(greaterThanOrEqualToConstant: 220).isActive = true
        rootStack.addArrangedSubview(tmxScrollView)
        tmxScrollView.widthAnchor.constraint(equalTo: rootStack.widthAnchor).isActive = true

        detailsButton.target = self
        detailsButton.action = #selector(toggleDetails)
        detailsButton.bezelStyle = .inline
        detailsButton.imagePosition = .imageLeading
        updateDetailsButton()
        rootStack.addArrangedSubview(detailsButton)

        logView.isEditable = false
        logView.isRichText = false
        logView.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        logView.textColor = .textColor
        logView.textContainerInset = NSSize(width: 10, height: 10)
        logView.backgroundColor = NSColor.textBackgroundColor.withAlphaComponent(0.96)
        logView.isVerticallyResizable = true
        logView.isHorizontallyResizable = true
        logView.autoresizingMask = [.width]
        logView.textContainer?.containerSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        logView.textContainer?.widthTracksTextView = false
        logView.string = ""

        logScrollView.borderType = .lineBorder
        logScrollView.hasVerticalScroller = true
        logScrollView.hasHorizontalScroller = true
        logScrollView.autohidesScrollers = true
        logScrollView.documentView = logView
        logScrollView.translatesAutoresizingMaskIntoConstraints = false
        logScrollView.heightAnchor.constraint(equalToConstant: 170).isActive = true
        logScrollView.isHidden = true
        rootStack.addArrangedSubview(logScrollView)
        logScrollView.widthAnchor.constraint(equalTo: rootStack.widthAnchor).isActive = true
    }

    private func configurePreviewTable() {
        let sourceColumn = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("source"))
        sourceColumn.title = "Source"
        sourceColumn.minWidth = 260
        sourceColumn.resizingMask = .autoresizingMask

        let targetColumn = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("target"))
        targetColumn.title = "Target"
        targetColumn.minWidth = 260
        targetColumn.resizingMask = .autoresizingMask

        tmxTableView.addTableColumn(sourceColumn)
        tmxTableView.addTableColumn(targetColumn)
        tmxTableView.delegate = self
        tmxTableView.dataSource = self
        tmxTableView.usesAlternatingRowBackgroundColors = true
        tmxTableView.gridStyleMask = [.solidHorizontalGridLineMask]
        tmxTableView.rowSizeStyle = .medium
        tmxTableView.allowsColumnResizing = true
        tmxTableView.allowsMultipleSelection = false
        tmxTableView.selectionHighlightStyle = .regular
        tmxTableView.columnAutoresizingStyle = .uniformColumnAutoresizingStyle
    }

    @objc private func showHeartEasterEgg(_ sender: NSClickGestureRecognizer) {
        guard let iconView = sender.view, let contentView = window?.contentView else {
            return
        }

        let iconFrame = iconView.convert(iconView.bounds, to: contentView)
        let startSize: CGFloat = 22
        let endSize: CGFloat = 46
        let drift = CGFloat(Int.random(in: -12...12))

        let heart = NSTextField(labelWithString: "❤️")
        heart.font = .systemFont(ofSize: 24)
        heart.alignment = .center
        heart.alphaValue = 0
        heart.isSelectable = false
        heart.frame = NSRect(
            x: iconFrame.midX - startSize / 2,
            y: iconFrame.midY - startSize / 2,
            width: startSize,
            height: startSize
        )

        contentView.addSubview(heart, positioned: .above, relativeTo: nil)

        let bloomFrame = NSRect(
            x: iconFrame.midX - endSize / 2 + drift,
            y: iconFrame.maxY + 10,
            width: endSize,
            height: endSize
        )
        let floatFrame = bloomFrame.offsetBy(dx: drift / 2, dy: 26)

        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.42
            context.timingFunction = CAMediaTimingFunction(name: .easeOut)
            heart.animator().alphaValue = 1
            heart.animator().frame = bloomFrame
        } completionHandler: {
            NSAnimationContext.runAnimationGroup { context in
                context.duration = 0.55
                context.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
                heart.animator().alphaValue = 0
                heart.animator().frame = floatFrame
            } completionHandler: {
                heart.removeFromSuperview()
            }
        }
    }

    @objc private func toggleDetails() {
        setDetailsExpanded(!detailsExpanded)
    }

    private func setDetailsExpanded(_ expanded: Bool) {
        detailsExpanded = expanded
        updateDetailsButton()
        window?.contentView?.layoutSubtreeIfNeeded()
    }

    private func updateDetailsButton() {
        detailsButton.title = detailsExpanded ? "Hide Preview and Run Log" : "Show Preview and Run Log"
        detailsButton.image = makeSymbol(detailsExpanded ? "chevron.down" : "chevron.right", fallback: "Details")
        logScrollView.isHidden = !detailsExpanded
    }

    func numberOfRows(in tableView: NSTableView) -> Int {
        tmxRows.count
    }

    func tableView(_ tableView: NSTableView, heightOfRow row: Int) -> CGFloat {
        66
    }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        guard row >= 0, row < tmxRows.count, let tableColumn else {
            return nil
        }

        let identifier = NSUserInterfaceItemIdentifier("\(tableColumn.identifier.rawValue)-cell")
        let cell = reusablePreviewCell(tableView: tableView, identifier: identifier)
        let previewRow = tmxRows[row]
        cell.textField?.stringValue = tableColumn.identifier.rawValue == "source" ? previewRow.source : previewRow.target
        return cell
    }

    private func reusablePreviewCell(
        tableView: NSTableView,
        identifier: NSUserInterfaceItemIdentifier
    ) -> NSTableCellView {
        if let cell = tableView.makeView(withIdentifier: identifier, owner: self) as? NSTableCellView {
            return cell
        }

        let cell = NSTableCellView()
        cell.identifier = identifier

        let textField = NSTextField(wrappingLabelWithString: "")
        textField.translatesAutoresizingMaskIntoConstraints = false
        textField.font = .systemFont(ofSize: 12)
        textField.textColor = .labelColor
        textField.maximumNumberOfLines = 3
        textField.lineBreakMode = .byTruncatingTail

        cell.addSubview(textField)
        cell.textField = textField
        NSLayoutConstraint.activate([
            textField.leadingAnchor.constraint(equalTo: cell.leadingAnchor, constant: 8),
            textField.trailingAnchor.constraint(equalTo: cell.trailingAnchor, constant: -8),
            textField.topAnchor.constraint(equalTo: cell.topAnchor, constant: 6),
            textField.bottomAnchor.constraint(lessThanOrEqualTo: cell.bottomAnchor, constant: -6)
        ])

        return cell
    }

    private func configurePathField(_ field: NSTextField, placeholder: String) {
        field.isEditable = false
        field.isSelectable = true
        field.isBezeled = true
        field.drawsBackground = true
        field.placeholderString = placeholder
        field.lineBreakMode = .byTruncatingMiddle
    }

    private func makePathRow(label: String, field: NSTextField, button: NSButton) -> NSView {
        let labelView = NSTextField(labelWithString: label)
        labelView.alignment = .right
        labelView.textColor = .secondaryLabelColor
        labelView.widthAnchor.constraint(equalToConstant: 92).isActive = true
        field.translatesAutoresizingMaskIntoConstraints = false
        field.heightAnchor.constraint(equalToConstant: 28).isActive = true
        button.widthAnchor.constraint(greaterThanOrEqualToConstant: 128).isActive = true

        let row = NSStackView(views: [labelView, field, button])
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 10
        row.distribution = .fill
        field.setContentHuggingPriority(.defaultLow, for: .horizontal)
        return row
    }

    @objc private func chooseInputFolder() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = "Choose"
        panel.message = "Choose the folder containing paired DOCX files."

        if panel.runModal() == .OK, let url = panel.url {
            inputURL = url
            inputField.stringValue = url.path
            previewSucceeded = false
            completedSelectionKey = nil
            clearLog()
            clearTmxPreview()
            setDetailsExpanded(false)
            statusLabel.stringValue = readinessStatus()
            updateControls()
        }
    }

    @objc private func chooseOutputFile() {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "aligned.tmx"
        panel.canCreateDirectories = true
        panel.message = "Choose where to write the TMX file."

        if panel.runModal() == .OK, let url = panel.url {
            outputURL = normalizedOutputURL(url)
            outputField.stringValue = outputURL?.path ?? url.path
            previewSucceeded = false
            completedSelectionKey = nil
            clearLog()
            clearTmxPreview()
            setDetailsExpanded(false)
            statusLabel.stringValue = readinessStatus()
            updateControls()
        }
    }

    private func normalizedOutputURL(_ url: URL) -> URL {
        if url.pathExtension.lowercased() == "tmx" {
            return url
        }
        return url.appendingPathExtension("tmx")
    }

    @objc private func runPreview() {
        run(.preview)
    }

    @objc private func runAlignment() {
        run(.align)
    }

    @objc private func cancelRun() {
        currentProcess?.terminate()
        statusLabel.stringValue = "Cancelling..."
    }

    @objc private func revealOutput() {
        guard let outputURL else {
            return
        }
        NSWorkspace.shared.activateFileViewerSelecting([outputURL])
    }

    private func selectedDevice() -> String {
        switch devicePopup.indexOfSelectedItem {
        case 1:
            return "mps"
        case 2:
            return "cpu"
        default:
            return "auto"
        }
    }

    private func run(_ mode: RunMode) {
        guard currentProcess == nil, let inputURL, let outputURL else {
            return
        }

        if mode == .preview {
            previewSucceeded = false
        }
        outputBuffer = ""
        runStartedAt = Date()
        progressStageStartedAt = nil
        progressStageName = nil

        clearLog()
        if mode == .align {
            clearTmxPreview()
            setDetailsExpanded(false)
        }
        appendLog("\(mode.title)\n")
        appendLog("Input:  \(inputURL.path)\n")
        appendLog("Output: \(outputURL.path)\n\n")

        let process = Process()
        currentProcess = process
        statusLabel.stringValue = mode.title
        progressIndicator.isIndeterminate = true
        progressIndicator.doubleValue = 0
        progressIndicator.startAnimation(nil)
        updateControls()

        process.executableURL = URL(fileURLWithPath: "/bin/sh")
        process.arguments = ["-lc", buildShellScript(mode: mode, inputURL: inputURL, outputURL: outputURL)]
        process.currentDirectoryURL = projectRoot

        var environment = ProcessInfo.processInfo.environment
        environment["LC_ALL"] = "en_US.UTF-8"
        environment["LANG"] = "en_US.UTF-8"
        environment["PYTHONUNBUFFERED"] = "1"
        environment["MEGALIGNER_EVENTS"] = "1"
        process.environment = environment

        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else {
                return
            }
            DispatchQueue.main.async {
                self?.handleProcessOutput(text)
            }
        }

        process.terminationHandler = { [weak self] finishedProcess in
            pipe.fileHandleForReading.readabilityHandler = nil
            DispatchQueue.main.async {
                self?.flushOutputBuffer()
                self?.finish(mode: mode, status: finishedProcess.terminationStatus)
            }
        }

        do {
            try process.run()
        } catch {
            currentProcess = nil
            progressIndicator.stopAnimation(nil)
            appendLog("\nFailed to start: \(error.localizedDescription)\n")
            statusLabel.stringValue = "Could not start."
            updateControls()
        }
    }

    private func buildShellScript(mode: RunMode, inputURL: URL, outputURL: URL) -> String {
        let outputDirectory = outputURL.deletingLastPathComponent()
        let supportRoot = applicationSupportDirectory()
        let hfCache = supportRoot.appendingPathComponent("hf-cache")
        let uvCache = supportRoot.appendingPathComponent("uv-cache")
        let uvInstall = supportRoot.appendingPathComponent("bin")
        let pythonInstall = supportRoot.appendingPathComponent("python")
        let virtualEnvironment = supportRoot.appendingPathComponent("venv")
        let bootstrap = projectRoot.appendingPathComponent("scripts/bootstrap_uv.sh")
        let setupPrefix: String
        switch mode {
        case .preview:
            setupPrefix = "Checking MEGAligner runtime if needed, then previewing detected bitext pairs."
        case .align:
            setupPrefix = "Setting up MEGAligner runtime and language model if needed. First launch can take several minutes; progress appears below."
        }

        var arguments = [
            shellQuote(inputURL.path),
            shellQuote(outputDirectory.path),
            "--combined-output",
            shellQuote(outputURL.path),
            "--model",
            shellQuote(defaultModel),
            "--workers",
            "1",
            "--sample-size",
            "20",
            "--device",
            shellQuote(selectedDevice())
        ]

        switch mode {
        case .preview:
            arguments.append("--dry-run")
        case .align:
            arguments.append(contentsOf: [
                "--yes",
                "--force",
                "--allow-model-download",
                "--verbose"
            ])
        }

        return """
        set -eu
        printf '%s\\n' \(shellQuote(setupPrefix))
        printf '%s\\n' 'Runtime cache: \(supportRoot.path)'
        mkdir -p \(shellQuote(supportRoot.path)) \(shellQuote(hfCache.path)) \(shellQuote(uvCache.path)) \(shellQuote(uvInstall.path)) \(shellQuote(pythonInstall.path)) \(shellQuote(outputDirectory.path))
        printf '%s\\n' 'Checking uv launcher...'
        cd \(shellQuote(supportRoot.path))
        uv_cmd=$(UV_VERSION=\(shellQuote(defaultUVVersion)) UV_INSTALL_DIR=\(shellQuote(uvInstall.path)) sh \(shellQuote(bootstrap.path)))
        printf '%s\\n' 'Starting aligner...'
        HF_HOME=\(shellQuote(hfCache.path)) \\
        SENTENCE_TRANSFORMERS_HOME=\(shellQuote(hfCache.path)) \\
        UV_CACHE_DIR=\(shellQuote(uvCache.path)) \\
        UV_MANAGED_PYTHON=1 \\
        UV_PYTHON_INSTALL_DIR=\(shellQuote(pythonInstall.path)) \\
        UV_PROJECT_ENVIRONMENT=\(shellQuote(virtualEnvironment.path)) \\
        PYTHONDONTWRITEBYTECODE=1 \\
        exec "$uv_cmd" run --project \(shellQuote(projectRoot.path)) --locked align-docx \(arguments.joined(separator: " "))
        """
    }

    private func finish(mode: RunMode, status: Int32) {
        currentProcess = nil
        runStartedAt = nil
        progressStageStartedAt = nil
        progressStageName = nil
        progressIndicator.stopAnimation(nil)

        if status == 0 {
            switch mode {
            case .preview:
                previewSucceeded = true
                progressIndicator.isIndeterminate = false
                progressIndicator.minValue = 0
                progressIndicator.maxValue = 1
                progressIndicator.doubleValue = 1
                statusLabel.stringValue = "Preview complete. Review details if needed, then click Align."
                setDetailsExpanded(true)
            case .align:
                completedSelectionKey = selectionKey()
                statusLabel.stringValue = "Done."
                if let outputURL {
                    loadTmxPreview(from: outputURL)
                    setDetailsExpanded(false)
                    appendLog("\nWrote: \(outputURL.path)\n")
                }
            }
        } else {
            if mode == .preview {
                previewSucceeded = false
            }
            statusLabel.stringValue = "Stopped with exit code \(status)."
            appendLog("\nProcess exited with code \(status).\n")
            setDetailsExpanded(true)
        }

        updateControls()
    }

    private func updateControls() {
        let hasPaths = inputURL != nil && outputURL != nil
        let isRunning = currentProcess != nil
        let completedCurrentSelection = hasPaths && completedSelectionKey == selectionKey()
        previewButton.isEnabled = hasPaths && !isRunning && !completedCurrentSelection
        alignButton.isEnabled = hasPaths && previewSucceeded && !isRunning && !completedCurrentSelection
        cancelButton.isEnabled = isRunning
        revealButton.isEnabled = outputURL.map { FileManager.default.fileExists(atPath: $0.path) } ?? false
        devicePopup.isEnabled = !isRunning
    }

    private func selectionKey() -> String? {
        guard let inputURL, let outputURL else {
            return nil
        }
        return "\(inputURL.standardizedFileURL.path)\n\(outputURL.standardizedFileURL.path)"
    }

    private func readinessStatus() -> String {
        switch (inputURL != nil, outputURL != nil) {
        case (false, false):
            return "Choose a DOCX folder and TMX output file."
        case (false, true):
            return "Choose a DOCX folder."
        case (true, false):
            return "Choose a TMX output file."
        case (true, true):
            return "Ready to preview."
        }
    }

    private func clearTmxPreview() {
        tmxRows = []
        tmxTableView.reloadData()
        tmxSummaryLabel.stringValue = "TMX Preview appears here after alignment."
    }

    private func loadTmxPreview(from url: URL) {
        do {
            var data = try Data(contentsOf: url)
            if let text = String(data: data, encoding: .utf8) {
                let sanitized = text.replacingOccurrences(
                    of: #"(?m)^<!DOCTYPE[^>]+>\s*"#,
                    with: "",
                    options: .regularExpression
                )
                data = sanitized.data(using: .utf8) ?? data
            }

            let previewParser = TmxPreviewParser()
            let parser = XMLParser(data: data)
            parser.delegate = previewParser

            if parser.parse(), previewParser.parseError == nil {
                tmxRows = previewParser.rows
                tmxTableView.reloadData()
                tmxSummaryLabel.stringValue = "TMX Preview - \(tmxRows.count) translation units"
            } else {
                tmxRows = []
                tmxTableView.reloadData()
                let message = previewParser.parseError?.localizedDescription ?? parser.parserError?.localizedDescription ?? "Unknown parser error"
                tmxSummaryLabel.stringValue = "TMX Preview unavailable: \(message)"
            }
        } catch {
            tmxRows = []
            tmxTableView.reloadData()
            tmxSummaryLabel.stringValue = "TMX Preview unavailable: \(error.localizedDescription)"
        }
    }

    private func clearLog() {
        logView.string = ""
    }

    private func appendLog(_ text: String) {
        let wasAtBottom = logView.visibleRect.maxY >= logView.bounds.maxY - 24
        let attributes: [NSAttributedString.Key: Any] = [
            .font: logView.font ?? NSFont.monospacedSystemFont(ofSize: 12, weight: .regular),
            .foregroundColor: NSColor.textColor
        ]
        logView.textStorage?.append(NSAttributedString(string: text, attributes: attributes))
        if wasAtBottom {
            logView.scrollToEndOfDocument(nil)
        }
    }

    private func handleProcessOutput(_ text: String) {
        let humanText = processEventLines(in: text, flush: false)
        if !humanText.isEmpty {
            appendLog(humanText)
            updateStatusFromOutput(humanText)
        }
    }

    private func flushOutputBuffer() {
        let humanText = processEventLines(in: "", flush: true)
        if !humanText.isEmpty {
            appendLog(humanText)
            updateStatusFromOutput(humanText)
        }
    }

    private func processEventLines(in text: String, flush: Bool) -> String {
        outputBuffer += text.replacingOccurrences(of: "\r", with: "\n")
        if outputBuffer.isEmpty {
            return ""
        }

        let normalized = outputBuffer
        var humanLines: [String] = []
        let endsWithNewline = normalized.hasSuffix("\n")
        var lines = normalized.components(separatedBy: .newlines)

        if !endsWithNewline && !flush {
            outputBuffer = lines.removeLast()
        } else {
            outputBuffer = ""
            if endsWithNewline, lines.last == "" {
                lines.removeLast()
            }
        }

        for rawLine in lines {
            if rawLine.isEmpty {
                continue
            }
            if rawLine.hasPrefix("MEGALIGNER_EVENT ") {
                let jsonText = String(rawLine.dropFirst("MEGALIGNER_EVENT ".count))
                handleEventJSON(jsonText)
            } else {
                humanLines.append(rawLine)
            }
        }

        guard !humanLines.isEmpty else {
            return ""
        }
        return humanLines.joined(separator: "\n") + "\n"
    }

    private func handleEventJSON(_ jsonText: String) {
        guard let data = jsonText.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data),
              let event = object as? [String: Any],
              let type = event["type"] as? String
        else {
            return
        }

        switch type {
        case "progress":
            guard
                let stage = event["stage"] as? String,
                let current = event["current"] as? Int,
                let total = event["total"] as? Int,
                let label = event["label"] as? String
            else {
                return
            }
            updateProgress(stage: stage, current: current, total: total, label: label)
        default:
            break
        }
    }

    private func updateProgress(stage: String, current: Int, total: Int, label: String) {
        if progressStageName != stage {
            progressStageName = stage
            progressStageStartedAt = Date()
        }
        progressIndicator.isIndeterminate = false
        progressIndicator.stopAnimation(nil)
        progressIndicator.minValue = 0
        progressIndicator.maxValue = Double(max(total, 1))
        progressIndicator.doubleValue = Double(current)

        let timing = timingSummary(current: current, total: total)
        statusLabel.stringValue = "\(stage) \(current) of \(total): \(label)\(timing)"
    }

    private func timingSummary(current: Int, total: Int) -> String {
        guard let startedAt = progressStageStartedAt else {
            return ""
        }
        let elapsed = max(0, Date().timeIntervalSince(startedAt))
        let elapsedText = formatDuration(elapsed)

        guard current > 0, total > current else {
            return " · elapsed \(elapsedText)"
        }

        let estimatedTotal = elapsed / Double(current) * Double(total)
        let remaining = max(0, estimatedTotal - elapsed)
        return " · elapsed \(elapsedText), about \(formatDuration(remaining)) left"
    }

    private func elapsedRunText() -> String {
        guard let startedAt = runStartedAt else {
            return ""
        }
        return " · elapsed \(formatDuration(Date().timeIntervalSince(startedAt)))"
    }

    private func formatDuration(_ seconds: TimeInterval) -> String {
        let totalSeconds = max(0, Int(seconds.rounded()))
        if totalSeconds < 60 {
            return "\(totalSeconds)s"
        }
        let minutes = totalSeconds / 60
        let seconds = totalSeconds % 60
        if minutes < 60 {
            return "\(minutes)m \(seconds)s"
        }
        let hours = minutes / 60
        let remainingMinutes = minutes % 60
        return "\(hours)h \(remainingMinutes)m"
    }

    private func updateStatusFromOutput(_ text: String) {
        let normalized = text.replacingOccurrences(of: "\r", with: "\n")
        for rawLine in normalized.components(separatedBy: .newlines) {
            let line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !line.isEmpty else {
                continue
            }

            if line.hasPrefix("Preparing language model:") {
                showIndeterminateStatus("Loading language model...")
            } else if line.hasPrefix("Checking local model cache") {
                showIndeterminateStatus("Checking model cache...")
            } else if line.hasPrefix("Encoding ") {
                showIndeterminateStatus(line)
            } else if line == "Language model ready." {
                showIndeterminateStatus("Language model ready.")
            } else if line == "Encoding complete. Starting pair alignment." {
                showIndeterminateStatus("Starting pair alignment.")
            } else if line.hasPrefix("Setting up MEGAligner runtime") {
                showIndeterminateStatus("Checking runtime setup...")
            } else if line.hasPrefix("Checking MEGAligner runtime") {
                showIndeterminateStatus("Checking runtime setup...")
            } else if line.hasPrefix("Discovery summary") {
                progressIndicator.isIndeterminate = false
                progressIndicator.stopAnimation(nil)
                progressIndicator.minValue = 0
                progressIndicator.maxValue = 1
                progressIndicator.doubleValue = 1
                statusLabel.stringValue = "Review detected pairs before aligning."
            } else if line == "Checking uv launcher..." {
                showIndeterminateStatus("Checking app runtime...")
            } else if line == "Starting aligner..." {
                showIndeterminateStatus("Starting aligner...")
            } else if line.hasPrefix("Installing pinned uv ") {
                showIndeterminateStatus("Installing app runtime...")
            } else if line.hasPrefix("Combined TMX:") {
                progressIndicator.isIndeterminate = false
                progressIndicator.stopAnimation(nil)
                progressIndicator.minValue = 0
                progressIndicator.maxValue = 1
                progressIndicator.doubleValue = 1
                statusLabel.stringValue = "Done."
            }
        }
    }

    private func showIndeterminateStatus(_ message: String) {
        progressStageName = nil
        progressStageStartedAt = nil
        progressIndicator.isIndeterminate = true
        progressIndicator.startAnimation(nil)
        statusLabel.stringValue = message + elapsedRunText()
    }

}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var mainWindowController: MainWindowController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        configureMenu()

        guard let projectRoot = findProjectRoot() else {
            let alert = NSAlert()
            alert.messageText = "MEGAligner could not find its project files."
            alert.informativeText = "Move the app next to the MEGAligner folder, or launch it with MEGALIGNER_ROOT set to the project path."
            alert.alertStyle = .critical
            alert.runModal()
            NSApp.terminate(nil)
            return
        }

        let controller = MainWindowController(projectRoot: projectRoot)
        mainWindowController = controller
        controller.showWindow(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    private func configureMenu() {
        let mainMenu = NSMenu()

        let appMenuItem = NSMenuItem()
        mainMenu.addItem(appMenuItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Quit \(appName)", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appMenuItem.submenu = appMenu

        let editMenuItem = NSMenuItem()
        mainMenu.addItem(editMenuItem)
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editMenuItem.submenu = editMenu

        NSApp.mainMenu = mainMenu
    }
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
