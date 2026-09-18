"""
工作流注册模块

在此文件中导入所有工作流，确保它们被注册到 WorkflowRegistry。
添加新工作流时，只需在此文件中添加导入语句即可。
"""

# 导入所有工作流（确保它们被注册）
from .paper_generation import workflow as paper_generation_workflow
from .paper_grading import workflow as paper_grading_workflow

# 导出所有工作流（可选，方便外部访问）
__all__ = [
    "paper_generation_workflow",
    "paper_grading_workflow",
]
