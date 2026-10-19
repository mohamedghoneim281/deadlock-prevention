CXX      ?= g++
CXXFLAGS ?= -O2 -std=c++17 -Wall -Wextra -Wpedantic

all: build/petri_engine

build/petri_engine: cpp/main.cpp cpp/engine.hpp cpp/petri_net.hpp
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -o $@ cpp/main.cpp

test: build/petri_engine
	python3 -m pytest -q tests

reproduce: build/petri_engine
	python3 scripts/run_all.py

clean:
	rm -rf build results/generated __pycache__ .pytest_cache

.PHONY: all test reproduce clean
