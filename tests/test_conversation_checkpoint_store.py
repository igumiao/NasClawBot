from hello_agents.checkpoints import ConversationCheckpoint, JSONConversationCheckpointStore


def test_json_checkpoint_store_saves_loads_lists_and_deletes(tmp_path):
    store = JSONConversationCheckpointStore(tmp_path)
    checkpoint = ConversationCheckpoint(
        session_id="session/with spaces",
        created_at="2026-06-03T10:00:00",
        saved_at="2026-06-03T10:01:00",
        history=[
            {
                "role": "user",
                "content": "Dune",
                "timestamp": "2026-06-03T10:00:00",
                "metadata": {},
            }
        ],
        metadata={"agent_name": "nasclawbot-agent"},
    )

    store.save(checkpoint)

    loaded = store.load("session/with spaces")
    assert loaded == checkpoint
    assert (tmp_path / "session-with-spaces.json").exists()

    summaries = store.list()
    assert len(summaries) == 1
    assert summaries[0].session_id == "session/with spaces"
    assert summaries[0].message_count == 1
    assert summaries[0].metadata["agent_name"] == "nasclawbot-agent"

    assert store.delete("session/with spaces") is True
    assert store.load("session/with spaces") is None
    assert store.delete("session/with spaces") is False
