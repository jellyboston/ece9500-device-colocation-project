// Exercise the actual firmware transport using native TCP and forced short writes.
#include <sys/socket.h>
#include <sys/select.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <fcntl.h>
#include <chrono>
#include <stdexcept>
#include <iostream>
#include <string>

static ssize_t short_send(int fd, const void *bytes, size_t length, int flags) {
    return ::send(fd, bytes, length > 3 ? 3 : length, flags);
}
#define send short_send
#include "tcp_record_sender.h"
#undef send

static uint32_t now() {
    return static_cast<uint32_t>(std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count());
}
static void require(bool result, const char *message) { if (!result) throw std::runtime_error(message); }

int main() {
    try {
        int listener = socket(AF_INET, SOCK_STREAM, 0);
        require(listener >= 0, "socket");
        sockaddr_in address = {};
        address.sin_family = AF_INET;
        address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        require(bind(listener, reinterpret_cast<sockaddr *>(&address), sizeof(address)) == 0, "bind");
        require(listen(listener, 1) == 0, "listen");
        socklen_t length = sizeof(address);
        getsockname(listener, reinterpret_cast<sockaddr *>(&address), &length);
        fcntl(listener, F_SETFL, O_NONBLOCK);
        TcpRecordSender sender;
        require(!sender.configure("invalid-address", 9000), "invalid IP rejected");
        require(sender.configure("127.0.0.1", ntohs(address.sin_port)), "configure");
        auto accept_sender = [&]() {
            int peer = -1;
            uint32_t start = now();
            while (uint32_t(now() - start) < 4000 && (peer < 0 || !sender.connected())) {
                sender.poll(now(), true);
                if (peer < 0) peer = accept(listener, nullptr, nullptr);
                usleep(1000);
            }
            require(peer >= 0 && sender.connected(), "nonblocking connection");
            fcntl(peer, F_SETFL, O_NONBLOCK);
            return peer;
        };
        int peer = accept_sender();
        require(!sender.submit("unfinished", 10), "newline required");
        std::string row = "PKT,1000,-45,1,LAP1\n";
        require(sender.submit(row.data(), row.size()), "submit");
        require(!sender.submit(row.data(), row.size()), "pending record protected");
        std::string received;
        uint32_t start = now();
        while (uint32_t(now() - start) < 2000 && received.size() < row.size()) {
            sender.poll(now(), true);
            char bytes[64];
            int count = recv(peer, bytes, sizeof(bytes), 0);
            if (count > 0) received.append(bytes, count);
            usleep(1000);
        }
        require(received == row && !sender.busy(), "short writes reconstruct exact record");
        require(sender.submit(row.data(), row.size()), "second submit");
        sender.poll(now(), true); // Only first 3 bytes have been written.
        sender.poll(now(), false); // Network loss must discard remainder.
        close(peer);
        require(!sender.busy() && !sender.connected(), "drop partial on disconnect");
        peer = accept_sender();
        require(sender.submit(row.data(), row.size()), "submit after reconnect");
        received.clear(); start = now();
        while (uint32_t(now() - start) < 2000 && received.size() < row.size()) {
            sender.poll(now(), true);
            char bytes[64]; int count = recv(peer, bytes, sizeof(bytes), 0);
            if (count > 0) received.append(bytes, count);
            usleep(1000);
        }
        require(received == row, "new connection starts on a record boundary");
        require(sender.connections == 2 && sender.dropped >= 3, "transport counters");
        sender.reset(); close(peer); close(listener);
        std::cout << "PASS: connect, short writes, newline validation, backpressure, reconnect, counters\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n'; return 1;
    }
}
