from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


class MakeAlignWrapperTests(unittest.TestCase):
    def test_optional_args_do_not_break_successful_run(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            fakebin = tmp / "fakebin"
            docs = tmp / "docs"
            fakebin.mkdir()
            docs.mkdir()
            (docs / "a.en.docx").touch()
            (docs / "a.ru.docx").touch()

            uv = fakebin / "uv"
            uv.write_text(
                "\n".join(
                    [
                        "#!/bin/sh",
                        'if [ "$1" = "--version" ]; then printf "%s\\n" "uv 0.11.15"; exit 0; fi',
                        'printf "%s\\n" "fake uv args: $*" >&2',
                        "exit 0",
                    ]
                ),
                encoding="utf-8",
            )
            osascript = fakebin / "osascript"
            osascript.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            for path in (uv, osascript):
                path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fakebin}{os.pathsep}{env.get('PATH', '')}",
                    "UV_BIN": str(uv),
                    "RUNNER": "native",
                    "DIR": str(docs),
                    "OUT": str(tmp / "out.tmx"),
                    "DRY_RUN": "0",
                    "PROFILE": "1",
                    "ALIGN_ARGS": "--batch-size 128",
                }
            )
            result = subprocess.run(
                ["sh", "scripts/make_align.sh"],
                cwd=repo_root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            expected_out = Path(os.path.realpath(tmp / "out.tmx"))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(f"Wrote: {expected_out}", result.stdout)
            self.assertIn("--allow-model-download --profile --batch-size 128", result.stderr)


if __name__ == "__main__":
    unittest.main()
