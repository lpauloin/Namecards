#!/usr/bin/env bash
set -e

echo "🔧 Installing system dependencies..."

# Homebrew
if ! command -v brew >/dev/null 2>&1; then
  echo "❌ Homebrew not found. Install it first:"
  echo "   https://brew.sh"
  exit 1
fi

brew update

echo "📦 Installing OpenSCAD..."
brew install openscad

echo "📦 Installing Inkscape..."
brew install --cask inkscape

echo "📦 Installing Python deps..."
python -m pip install --upgrade pip
pip install -r requirements.txt

echo "✅ All dependencies installed"