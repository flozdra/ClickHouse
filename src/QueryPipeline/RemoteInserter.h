#pragma once

#include <Core/Block.h>
#include <IO/ConnectionTimeouts.h>

namespace DB
{

class ClientInfo;
class Connection;
class ReadBuffer;
struct Settings;


/** Allow to execute INSERT query on remote server and send data for it.
  */
class RemoteInserter
{
public:
    RemoteInserter(
        Connection & connection_,
        const ConnectionTimeouts & timeouts,
        const String & query_,
        const Settings & settings_,
        const ClientInfo & client_info_);

    void initialize();

    Block initializeAndGetHeader()
    {
        initialize();
        return header;
    }

    void write(Block block);
    void onFinish();

    /// Send pre-serialized and possibly pre-compressed block of data, that will be read from 'input'.
    void writePrepared(ReadBuffer & buf, size_t size = 0);

    ~RemoteInserter();

    const Block & getHeader() const { return header; }
    UInt64 getServerRevision() const { return server_revision; }

private:
    const Settings & insert_settings;
    const ClientInfo & client_info;
    const ConnectionTimeouts & timeouts;

    Connection & connection;
    String query;

    Block header;
    bool finished = false;
    UInt64 server_revision;
};

}
