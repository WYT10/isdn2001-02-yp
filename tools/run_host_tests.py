"""Compile and run the actual C conversion/timing code with a native compiler."""
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parents[1]
compiler = shutil.which("gcc")
if not compiler:
    raise SystemExit("gcc is required on PATH (for example Strawberry/MinGW or GCC on Linux).")
build = root / ".pio" / "host"
build.mkdir(parents=True, exist_ok=True)
binary = build / "test_flow_sensor.exe"
command = [compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-Iinclude",
           "-DFLOW_SENSOR_HOST_TEST", "src/flow_sensor.c", "test/host/test_flow_sensor.c",
           "-o", str(binary), "-lm"]
subprocess.run(command, cwd=root, check=True, timeout=60)
result = subprocess.run([str(binary)], cwd=root, check=True, timeout=30,
                        capture_output=True, text=True)
print(result.stdout, end="")
output = root / "output" / "hardware" / "host-tests.txt"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(result.stdout, encoding="utf-8")
