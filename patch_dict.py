import re
with open("app/main.py", "r") as f:
    content = f.read()
content = content.replace(
    'c_dict, r_list = parser.parse_entry_point(ep_file, ep_key)',
    'ep_filename = ep_file if isinstance(ep_file, str) else ep_file["file"]\n                    c_dict, r_list = parser.parse_entry_point(ep_filename, ep_key)'
)
with open("app/main.py", "w") as f:
    f.write(content)
