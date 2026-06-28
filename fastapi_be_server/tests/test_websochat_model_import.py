import importlib


def test_websochat_model_modules_import_without_name_collision():
    websochat_models = importlib.import_module("app.models.websochat")
    story_agent_models = importlib.import_module("app.models.story_agent")

    assert websochat_models.WebsochatContextChunk.__tablename__ == "tb_story_agent_context_chunk"
    assert story_agent_models.StoryAgentContextChunk.__tablename__ == "tb_story_agent_context_chunk"
