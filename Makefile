PYTHON := python3
name ?=

.PHONY: help wallet show-wallet 9000 9001 9002

help:
	@echo "make wallet name=<name>       Create a named wallet"
	@echo "make show-wallet name=<name>  Show a named wallet"
	@echo "make 9000                     Start node on port 9000 as alice"
	@echo "make 9001                     Start node on port 9001 as bob and connect to 9000"
	@echo "make 9002                     Start node on port 9002 as charlie and connect to 9000"

wallet:
	@test -n "$(name)" || (echo "name is required" && exit 1)
	$(PYTHON) -m wallet.cli create --name $(name)

show-wallet:
	@test -n "$(name)" || (echo "name is required" && exit 1)
	$(PYTHON) -m wallet.cli show --name $(name)

9000:
	$(PYTHON) -m node.cli --port 9000 --wallet-name alice

9001:
	$(PYTHON) -m node.cli --port 9001 --peer 127.0.0.1:9000 --wallet-name bob

9002:
	$(PYTHON) -m node.cli --port 9002 --peer 127.0.0.1:9000 --wallet-name charlie
