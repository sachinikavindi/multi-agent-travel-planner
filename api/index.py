import os
import sys

# Add parent directory to sys.path to resolve root-level imports on Vercel
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
