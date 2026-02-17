#!/usr/bin/env python3
"""Entry point for running ClaudeWatch as a module: python -m claudewatch"""

from claudewatch.app import ClaudeWatch

if __name__ == '__main__':
    ClaudeWatch().run()
