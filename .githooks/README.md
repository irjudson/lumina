# Git Hooks

This directory contains git hooks to ensure code quality at different stages of development.

## Setup

Install the hooks by creating symlinks:

```bash
ln -sf ../../.githooks/pre-commit .git/hooks/pre-commit
ln -sf ../../.githooks/pre-push .git/hooks/pre-push
```

## Hook Strategy

We use a two-stage approach to balance speed and thoroughness:

### Pre-Commit Hook (Fast - ~5 seconds)

Runs **before every commit** to catch code quality issues early:

1. **Black formatting check** - Ensures code is formatted
2. **isort import sorting** - Ensures imports are properly organized
3. **flake8 linting** - Checks for code quality issues
4. **mypy type checking** - Validates type hints
5. **Common issues check** - Checks for debugger statements, print statements in core code

These are **fast checks** that don't require external services, so commits stay quick.

### Pre-Push Hook (Thorough - ~30 seconds)

Runs **before every push** to ensure tests pass:

1. **Pytest test suite** - Runs all unit tests (parallel execution)
2. **Docker build check** - Verifies Docker images build (only if Dockerfile changed)

Tests require database services, so we run them at push time to keep commits fast while still validating before sharing code.

## If Pre-Commit Hook Fails

**Black formatting issues:**
```bash
black lumina/ tests/
git add -u
# Hook will pass on retry
```

**isort import sorting issues:**
```bash
isort lumina/ tests/
git add -u
# Hook will pass on retry
```

**flake8 linting issues:**
```bash
# View the issues
flake8 lumina/ tests/

# Fix them manually, then:
git add -u
```

**mypy type checking issues:**
```bash
# View the issues
mypy lumina/

# Fix them manually, then:
git add -u
```

**Debugger statements found:**
Remove `import pdb`, `pdb.set_trace()`, or `breakpoint()` calls:
```bash
# Find them
grep -r "import pdb\|breakpoint()" lumina/

# Remove them, then
git add -u
```

## If Pre-Push Hook Fails

**Test failures:**
Fix the failing tests, then:
```bash
git add -u
git commit -m "fix: resolve test failures"
git push
```

**Docker build failures:**
Fix the Dockerfile or dependencies, then:
```bash
git add -u
git commit -m "fix: resolve Docker build issues"
git push
```

## Skipping Hooks (Not Recommended)

In emergencies only:
```bash
git commit --no-verify  # Skip pre-commit hook
git push --no-verify    # Skip pre-push hook
```

**⚠️ Warning:** Skipping hooks may cause CI failures on GitHub!

## Benefits

- ✅ **Fast commits**: Quality checks run quickly without database dependencies
- ✅ **Thorough pushes**: Tests validate correctness before sharing code
- ✅ **Catches issues early**: Problems found locally, not in CI
- ✅ **Better workflow**: Commit often (fast), push when ready (validated)
- ✅ **CI always succeeds**: Local checks match CI checks
