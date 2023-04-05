"""
Bit of a hack, but load_dotenv needs to be called before most other modules.
"""
from dotenv import load_dotenv

load_dotenv()
load_dotenv(".env.local")

# Dummy value that can be imported to allow relative imports, and avoid unused
# import warnings.
DUMMY = ()
