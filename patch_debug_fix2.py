import re

with open("app/main.py", "r") as f:
    content = f.read()

content = content.replace('print("IS DIR?", package_path.is_dir())', 'print("PATH:", package_path, "IS DIR?", package_path.is_dir())')

with open("app/main.py", "w") as f:
    f.write(content)
