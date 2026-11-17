"""Compile and run the portable sensor calculations and CLI parser with native GCC."""
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parents[1]
compiler = shutil.which("gcc")
if not compiler:
    raise SystemExit("gcc is required on PATH (for example Strawberry/MinGW or GCC on Linux).")
build = root / ".pio" / "host"
build.mkdir(parents=True, exist_ok=True)
results = []
for name, define in (("flow_sensor", "FLOW_SENSOR_HOST_TEST"), ("cli", "CLI_HOST_TEST")):
    binary = build / f"test_{name}.exe"
    command = [compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-Iinclude",
               f"-D{define}", f"src/{name}.c", f"test/host/test_{name}.c",
               "-o", str(binary), "-lm"]
    subprocess.run(command, cwd=root, check=True, timeout=60)
    result = subprocess.run([str(binary)], cwd=root, check=True, timeout=30,
                            capture_output=True, text=True)
    print(result.stdout, end="")
    results.append(result.stdout)
output = root / "output" / "hardware" / "host-tests.txt"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text("".join(results), encoding="utf-8")
