# -*- coding: utf-8 -*-
"""
HMI 部署后端。

提供：
  - base.py: HmiBackend 抽象基类
  - classic/: Basic/Comfort 经典 HMI XML 后端
  - unified/: WinCC Unified 直接对象模型后端
"""

from .base import HmiBackend

__all__ = ["HmiBackend"]
