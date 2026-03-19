---
description: This file describes the general guidelines for contributing to the project.
---

# Contribution Guidelines

We do test driven development. First write a test for the new feature or bug fix, then implement the code to pass the test. This ensures that our code is testable, well-tested and maintainable.

To test the code use:
```bash
uv run pytest tests/
```
When doing small investigations, always try to do them in form of a pytest instead of executing a code snippet etc.

At the end ALL tests shall pass.

## Linting and Formatting
We use `uv run pylint` to check for linting issues. Always do this and fix any issues before finishing.

## Documentation
When adding new features or making significant changes, please update the documentation accordingly with markdown files in docs/ directory.
