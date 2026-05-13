from unittest import TestCase

from understand_agent.model import OPENAI_BASE_URL, OpenAIResponsesClient, build_response_create_kwargs


class OpenAIResponsesClientTest(TestCase):
    def test_default_base_url_points_to_local_proxy(self) -> None:
        client = OpenAIResponsesClient()

        self.assertEqual(OPENAI_BASE_URL, "http://127.0.0.1:8787/v1")
        self.assertEqual(client.base_url, "http://127.0.0.1:8787/v1")

    def test_response_create_kwargs_are_minimal_for_proxy_compatibility(self) -> None:
        kwargs = build_response_create_kwargs(
            model="gpt-5.5",
            instructions="instructions",
            tools=[],
            input_items=[],
        )

        self.assertEqual(
            kwargs,
            {
                "model": "gpt-5.5",
                "instructions": "instructions",
                "tools": [],
                "input": [],
            },
        )
        self.assertNotIn("store", kwargs)
        self.assertNotIn("tool_choice", kwargs)
        self.assertNotIn("reasoning", kwargs)
