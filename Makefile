.PHONY: build install build-worker clean clean-all

build: install
	cd web && npm run build

install:
	uv sync
	cd web && npm install

build-worker:
	/opt/podman/bin/podman build -t rhclaw-worker -f worker/Containerfile worker/

clean:
	rm -rf web/dist

clean-all: clean
	rm -rf data/
