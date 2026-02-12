from core.secure_config import conf
import os

print(f"Active Config Path: {conf.config_path}")
print(f"Config Exists: {os.path.exists(conf.config_path)}")
print(f"Current Config Keys: {list(conf.config.keys())}")
if "SourceFolders" in conf.config:
    print(f"SourceFolders: {conf.config['SourceFolders']}")
else:
    print("SourceFolders not present.")
