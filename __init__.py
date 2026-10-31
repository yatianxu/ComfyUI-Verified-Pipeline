"""ComfyUI stage orchestration nodes. No project/media data is bundled."""
from .nodes import VerifiedPipelineSettings, VerifiedPipelineStage, VerifiedPipelineExecute, register_routes

NODE_CLASS_MAPPINGS = {
    'VerifiedPipelineSettings': VerifiedPipelineSettings,
    'VerifiedPipelineStage': VerifiedPipelineStage,
    'VerifiedPipelineExecute': VerifiedPipelineExecute,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    'VerifiedPipelineSettings': 'Verified Pipeline · Settings',
    'VerifiedPipelineStage': 'Verified Pipeline · Stage',
    'VerifiedPipelineExecute': 'Verified Pipeline · Execute / Status',
}
WEB_DIRECTORY = './web'
__version__ = '0.1.0'
__all__ = ['NODE_CLASS_MAPPINGS','NODE_DISPLAY_NAME_MAPPINGS','WEB_DIRECTORY']
register_routes()
