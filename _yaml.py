import yaml
from yaml import load

file = open('user.conf', 'r')
config = load(file, yaml.BaseLoader)
print(config)
