"""tools/filesystem_tools.py -- Enhanced filesystem tools.

Directory tree visualization, file info, safe delete, batch operations."""

from tools import ToolDef, ToolRegistry


def register(registry: ToolRegistry):
    from filesystem import list_directory as tree_list, get_file_info as file_info, safe_delete, search_files as fs_search

    def directory_tree(dir_path: str, max_depth: int = 2) -> str:
        """Show a tree visualization of a directory."""
        return tree_list(dir_path, max_depth=max_depth)

    def file_info_tool(file_path: str) -> str:
        """Get detailed information about a file (size, type, modified date)."""
        return file_info(file_path)

    def safe_delete_tool(file_path: str) -> str:
        """Safely delete a file (moves to recycle bin). REQUIRES CONFIRMATION."""
        return f"DELETE_REQUESTED: {file_path}"

    def search_files_tool(pattern: str, directory: str = ".") -> str:
        """Search for files matching a glob pattern (e.g. '**/*.py')."""
        return fs_search(pattern, directory)

    registry.register(ToolDef(
        name="directory_tree",
        description="Show a tree visualization of a directory's contents.",
        parameters={"type": "object", "properties": {"dir_path": {"type": "string", "description": "Path to the directory"}, "max_depth": {"type": "integer", "description": "Max depth (default 2)"}}, "required": ["dir_path"]},
        handler=directory_tree,
        safety_level="safe",
    ))
    registry.register(ToolDef(
        name="file_info",
        description="Get detailed info about a file: size, type, language, modified date.",
        parameters={"type": "object", "properties": {"file_path": {"type": "string", "description": "Path to the file"}}, "required": ["file_path"]},
        handler=file_info_tool,
        safety_level="safe",
    ))
    registry.register(ToolDef(
        name="safe_delete",
        description="Safely delete a file (moves to recycle bin when possible).",
        parameters={"type": "object", "properties": {"file_path": {"type": "string", "description": "Path to the file to delete"}}, "required": ["file_path"]},
        handler=safe_delete_tool,
        safety_level="consequential",
    ))
    registry.register(ToolDef(
        name="search_files",
        description="Search for files matching a glob pattern (e.g. '**/*.py', 'src/**/*.js').",
        parameters={"type": "object", "properties": {"pattern": {"type": "string", "description": "Glob pattern"}, "directory": {"type": "string", "description": "Directory to search in (default: .)"}}, "required": ["pattern"]},
        handler=search_files_tool,
        safety_level="safe",
    ))