#!/bin/bash
set -e

# Configuration
VERSION="0.0.1"
BASE_URL="https://github.com/SeimSoft/xyce-python/releases/download/release/${VERSION}"
PACKAGE_DIR="src/opens_suite/xyce"

# Detect System
OS="$(uname -s)"
ARCH="$(uname -m)"

case "${OS}" in
    Darwin*)
        PLATFORM="darwin"
        ZIP_FILE="xyce-macos-latest.zip"
        # Optional: Check for intel vs arm if the release eventually separates them
        # For now, only latest and intel-26 are listed.
        ;;
    Linux*)
        PLATFORM="linux"
        ZIP_FILE="xyce-ubuntu-latest.zip"
        ;;
    *)
        echo "Unsupported OS: ${OS}"
        exit 1
        ;;
esac

echo "Detected Platform: ${PLATFORM} (${ARCH})"
echo "Downloading Xyce ${VERSION} from ${BASE_URL}/${ZIP_FILE}..."

mkdir -p "${PACKAGE_DIR}/${PLATFORM}"
cd "${PACKAGE_DIR}/${PLATFORM}"

# Download
curl -L "${BASE_URL}/${ZIP_FILE}" -o xyce.zip

# Extract
echo "Extracting..."
unzip -o xyce.zip
# The zip contains a tar.gz based on my previous inspection
TAR_FILE=$(ls *.tar.gz)
tar -xzf "${TAR_FILE}"
rm xyce.zip "${TAR_FILE}"

echo "Xyce setup complete in ${PACKAGE_DIR}/${PLATFORM}"
