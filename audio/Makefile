CC      = gcc
# Pi 4 (Cortex-A72 ARMv8) 최적화. cross-compile 방지로 march 없이 -O2만 사용.
CFLAGS  = -O2 -Wall -Wextra -pipe
LDFLAGS = -lasound -lm -lpthread

TARGET  = karaoke_audio
SRC     = karaoke_audio.c

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

clean:
	rm -f $(TARGET)

.PHONY: all clean
