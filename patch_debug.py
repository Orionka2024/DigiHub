import re

with open("app/main.py", "r") as f:
    content = f.read()

content = content.replace('if "requirements" not in manifest and package_path.is_dir():', 'print("IS DIR?", package_path.is_dir()); if "requirements" not in manifest and package_path.is_dir():')

with open("app/main.py", "w") as f:
    f.write(content)
