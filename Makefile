# alvalllm — Makefile (spec: make = 1 binaire; make install = system)
# Style aligné sur ffsr.

CC      ?= gcc
CFLAGS  ?= -O2 -Wall -Wextra
CFLAGS  += -Isrc $(shell pkg-config --cflags jansson)
LDLIBS   = $(shell pkg-config --libs jansson)

SRC     = src
BIN     = alvalllm

PREFIX   ?= /usr/local
BINDIR   ?= $(PREFIX)/bin
DATADIR  ?= $(PREFIX)/share/alvalllm

all: $(BIN)

$(BIN): $(SRC)/main.c $(SRC)/params.c $(SRC)/params.h
	$(CC) $(CFLAGS) -o $@ $(SRC)/main.c $(SRC)/params.c $(LDLIBS)

install: all
	install -d $(DESTDIR)$(BINDIR) $(DESTDIR)$(DATADIR)
	install -m 0755 $(BIN) $(DESTDIR)$(BINDIR)/
	install -m 0644 data/params.json.example $(DESTDIR)$(DATADIR)/

uninstall:
	rm -f $(DESTDIR)$(BINDIR)/$(BIN)
	rm -rf $(DESTDIR)$(DATADIR)

clean:
	rm -f $(BIN) $(SRC)/*.o

.PHONY: all install uninstall clean
