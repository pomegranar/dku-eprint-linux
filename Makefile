# Convenience targets.  'make install' is the same thing install.sh does.
NAME    := dku-eprint
VERSION := 1.0.0
DIST    := $(NAME)-$(VERSION)

.PHONY: help test install uninstall dist rpm deb arch clean

help:
	@echo "make test       run the test suite (no network needed)"
	@echo "make install    install system-wide (needs root)"
	@echo "make uninstall  remove it again (needs root)"
	@echo "make dist       build $(DIST).tar.gz"
	@echo "make rpm        build an RPM   (needs rpmbuild)"
	@echo "make deb        build a .deb   (needs dpkg-buildpackage)"
	@echo "make arch       build a pkg    (needs makepkg)"

test:
	python3 -m unittest discover -s tests -v

install:
	./install.sh

uninstall:
	./uninstall.sh

dist: clean
	@mkdir -p dist
	git archive --format=tar.gz --prefix=$(DIST)/ -o dist/$(DIST).tar.gz HEAD

rpm: dist
	@mkdir -p build/rpm/SOURCES build/rpm/SPECS
	cp dist/$(DIST).tar.gz build/rpm/SOURCES/
	cp packaging/rpm/$(NAME).spec build/rpm/SPECS/
	rpmbuild --define "_topdir $(CURDIR)/build/rpm" -bb build/rpm/SPECS/$(NAME).spec
	@echo "==> build/rpm/RPMS/noarch/"

deb:
	@test -d debian || cp -r packaging/debian debian
	dpkg-buildpackage -us -uc -b
	@echo "==> ../$(NAME)_$(VERSION)*.deb"

arch: dist
	@mkdir -p build/arch
	cp packaging/arch/PKGBUILD packaging/arch/dku-eprint.install build/arch/
	cp dist/$(DIST).tar.gz build/arch/
	cd build/arch && makepkg -f
	@echo "==> build/arch/"

clean:
	rm -rf build dist debian
	find . -name __pycache__ -prune -exec rm -rf {} +
