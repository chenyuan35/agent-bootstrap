#!/usr/bin/env python3
"""
Key Format Catalog - Recognition rate test.

Tests key prefix recognition against known providers.
Target: 80%+ recognition rate.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from catalog import identify_by_prefix, get_format_by_provider_name, provider_families, _KEY_FORMAT_DB


# Test cases: (api_key, expected_provider, description)
TEST_KEYS = [
    # OpenAI
    ("sk-abc123def456ghi789jkl012mno345pqr678stu901", "openai", "OpenAI standard key"),
    ("sk-proj-abc123def456ghi789jkl012mno345pqr678stu901", "openai", "OpenAI project key"),
    ("sk-abc123def456ghi789jkl012$org-abc123def456", "openai", "OpenAI org key"),
    # Anthropic
    ("sk-ant-abc123def456ghi789jkl012mno345pqr678stu901", "anthropic", "Anthropic key"),
    # Google
    ("AIzaSqwertyuiopasdfghjklzxcvbnm123456789", "google", "Google AI Studio key"),
    # Cohere
    ("co-abc123def456ghi789jkl012mno345pqr678stu901", "cohere", "Cohere key"),
    ("ps-abc123def456ghi789", "cohere", "Cohere PS key"),
    # Mistral
    ("mtl-abc123def456ghi789jkl012mno345pqr678stu901", "mistral", "Mistral key"),
    # Groq
    ("gsk_abc123def456ghi789jkl012mno345pqr678stu901", "groq", "Groq key"),
    # Together
    ("abcdef1234567890abcdef1234567890ab", "together", "Together AI key (32-char hex)"),
    # Replicate
    ("r8_abc123def456ghi789jkl012mno345pqr678stu901", "replicate", "Replicate key"),
    # Hugging Face
    ("hf_abc123def456ghi789jkl012mno345pqr678stu901", "huggingface", "Hugging Face token"),
    # OpenRouter
    ("sk-or-abc123def456ghi789jkl012mno345pqr678stu901", "openrouter", "OpenRouter key"),
    # Azure (GUID-like)
    ("abc12345-6789-0123-4567-890abcdef12345", "azure", "Azure OpenAI key"),
    # Local
    ("local_development_key_123", "local", "Local dev key"),
    ("abcdef1234567890abcdef123456789012", "local", "Generic 32-char key"),
]


def test_recognition_rate():
    """Test key prefix recognition rate"""
    total = len(TEST_KEYS)
    recognized = 0
    failed = []

    print(f"Testing {total} key formats...\n")

    for key, expected, desc in TEST_KEYS:
        result = identify_by_prefix(key)
        status = "✓" if result == expected else "✗"
        if result == expected:
            recognized += 1
        else:
            failed.append((desc, key[:20] + "...", expected, result))

        print(f"  {status} {desc}: {result or 'None'} (expected: {expected})")

    rate = recognized / total * 100
    print(f"\nRecognition rate: {recognized}/{total} = {rate:.1f}%")
    print(f"Target: 80%+")

    if failed:
        print(f"\nFailed ({len(failed)}):")
        for desc, key_preview, expected, got in failed:
            print(f"  - {desc}: got '{got}' (expected '{expected}')")

    return rate >= 80.0, rate, failed


def test_coverage():
    """Test provider coverage"""
    families = provider_families()
    print(f"\nProvider families covered: {len(families)}")
    for provider, formats in families.items():
        print(f"  - {provider}: {len(formats)} format(s)")

    # Check for common providers
    expected_providers = ["openai", "anthropic", "google", "cohere", "mistral",
                          "groq", "together", "replicate", "huggingface", "openrouter", "azure", "local"]
    missing = [p for p in expected_providers if p not in families]
    if missing:
        print(f"\nMissing providers: {missing}")
    else:
        print(f"\nAll expected providers covered ✓")

    return len(families) >= 10


if __name__ == "__main__":
    print("=" * 50)
    print("Key Format Recognition Test")
    print("=" * 50)

    rate_ok, rate, failed = test_recognition_rate()
    coverage_ok = test_coverage()

    print("\n" + "=" * 50)
    print("Summary:")
    print(f"  Recognition rate: {rate:.1f}% {'✓' if rate_ok else '✗'} (target >= 80%)")
    print(f"  Provider coverage: {len(provider_families())} providers {'✓' if coverage_ok else '✗'} (target >= 10)")
    print("=" * 50)

    sys.exit(0 if (rate_ok and coverage_ok) else 1)
