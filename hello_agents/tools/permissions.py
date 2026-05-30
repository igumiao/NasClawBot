"""Tool permission levels for HelloAgents runtime."""

from enum import Enum


class ToolPermission(Enum):
    READONLY = "readonly"
    SIDE_EFFECT = "side_effect"
    DESTRUCTIVE = "destructive"
