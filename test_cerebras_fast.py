#!/usr/bin/env python3
"""Test Cerebras API with faster model"""
import time
import os
from langchain_cerebras import ChatCerebras
from langchain_core.messages import HumanMessage

os.environ["CEREBRAS_API_KEY"] = "csk-c9yrx2tfdrfyted3w5ckvnprm64rh48frrhvpevv9j26982v"

def test_models():
    """Test different Cerebras models"""
    models = [
        "llama-4-scout-17b-16e-instruct",  # Fastest: 2600 tokens/s
        "llama-3.3-70b",  # Stable, fast
    ]

    for model_name in models:
        print(f"\n{'='*60}")
        print(f"Testing: {model_name}")
        print('='*60)

        try:
            llm = ChatCerebras(model=model_name, timeout=15, max_retries=1)

            start = time.time()
            response = llm.invoke([HumanMessage(content="Say hello")])
            elapsed = time.time() - start

            print(f"✅ Response: {response.content}")
            print(f"⏱️  Time: {elapsed:.2f}s")

        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_models()
