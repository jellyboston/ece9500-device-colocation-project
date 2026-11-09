#pragma once

// Bounded, nonblocking TCP transport. poll() runs in loop(), never Wi-Fi callbacks.
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#ifdef ARDUINO
#include <lwip/sockets.h>
#include <lwip/inet.h>
#else
#include <sys/socket.h>
#include <sys/select.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <unistd.h>
#endif

class TcpRecordSender {
public:
    static constexpr size_t CAPACITY = 1024;
    uint32_t connections = 0, dropped = 0, failures = 0;

    bool configure(const char *host, uint16_t port) {
        address = {};
        address.sin_family = AF_INET;
        address.sin_port = htons(port);
        return inet_pton(AF_INET, host, &address.sin_addr) == 1 && port != 0;
    }
    bool connected() const { return state == ONLINE; }
    bool busy() const { return size != 0; }

    bool submit(const char *record, size_t length) {
        if (!connected() || busy() || length == 0 || length > CAPACITY || record[length - 1] != '\n') {
            ++dropped;
            return false;
        }
        memcpy(buffer, record, length);
        size = length;
        offset = 0;
        return true;
    }

    void poll(uint32_t now, bool networkReady) {
        if (!networkReady) { reset(); return; }
        if (state == OFFLINE) {
            if (attempted && uint32_t(now - lastAttempt) < 2000) return;
            attempted = true;
            lastAttempt = now;
            fd = socket(AF_INET, SOCK_STREAM, 0);
            if (fd < 0) { ++failures; return; }
            int flags = fcntl(fd, F_GETFL, 0);
            if (flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0) { fail(); return; }
            int enabled = 1;
            setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &enabled, sizeof(enabled));
            setsockopt(fd, SOL_SOCKET, SO_KEEPALIVE, &enabled, sizeof(enabled));
            int result = ::connect(fd, reinterpret_cast<sockaddr *>(&address), sizeof(address));
            if (result == 0) { state = ONLINE; ++connections; lastProgress = now; }
            else if (errno == EINPROGRESS || errno == EWOULDBLOCK) state = CONNECTING;
            else fail();
            return;
        }
        if (state == CONNECTING) {
            fd_set writes, errors;
            FD_ZERO(&writes); FD_ZERO(&errors);
            FD_SET(fd, &writes); FD_SET(fd, &errors);
            timeval timeout = {};
            int result = select(fd + 1, nullptr, &writes, &errors, &timeout);
            if (result < 0) { if (errno != EINTR) fail(); return; }
            if (result > 0) {
                int error = 0;
                socklen_t length = sizeof(error);
                if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &length) < 0 || error != 0) { fail(); return; }
                state = ONLINE; ++connections; lastProgress = now;
            } else if (uint32_t(now - lastAttempt) >= 2000) fail();
            return;
        }
        char byte;
        int peek = recv(fd, &byte, 1, MSG_PEEK | MSG_DONTWAIT);
        if (peek == 0 || (peek < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)) { fail(); return; }
        if (!busy()) { lastProgress = now; return; }
        int options = MSG_DONTWAIT;
#ifdef MSG_NOSIGNAL
        options |= MSG_NOSIGNAL;
#endif
        int sent = send(fd, buffer + offset, size - offset, options);
        if (sent > 0) {
            offset += static_cast<size_t>(sent);
            lastProgress = now;
            if (offset == size) size = offset = 0;
        } else if (sent == 0 || (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)) fail();
        else if (uint32_t(now - lastProgress) >= 5000) fail();
    }

    void reset() {
        if (fd >= 0) ::close(fd);
        fd = -1;
        state = OFFLINE;
        if (size) ++dropped;
        size = offset = 0; // Never resume a partial record on a new connection.
    }
    ~TcpRecordSender() { reset(); }

private:
    enum State { OFFLINE, CONNECTING, ONLINE } state = OFFLINE;
    int fd = -1;
    sockaddr_in address = {};
    char buffer[CAPACITY];
    size_t size = 0, offset = 0;
    bool attempted = false;
    uint32_t lastAttempt = 0, lastProgress = 0;
    void fail() { ++failures; reset(); }
};
