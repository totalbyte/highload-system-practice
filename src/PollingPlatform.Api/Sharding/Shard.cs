using Microsoft.EntityFrameworkCore;
using PollingPlatform.Api.Data;

namespace PollingPlatform.Api.Sharding;

/// <summary>
/// Один шард (лаба 7, ADR 0055): пара Primary + Replica з лаби 6 зі своїм монітором вузлів. Shard A — це сервіси
/// postgres / postgres-replica, на ньому ж таблиця users і послідовність poll_ids; Shard B — postgres-shard-b (+ репліка).
/// </summary>
public sealed class Shard(int index, DbContextOptions<AppDbContext> primary, DbContextOptions<AppDbContext>? replica, DbNodeMonitor monitor)
{
    public int Index => index;
    public string Name => ShardRouter.Name(index);
    public DbContextOptions<AppDbContext> PrimaryOptions => primary;
    /// <summary>null — репліку вимкнено (READ_REPLICA_ENABLED=false) або не задано.</summary>
    public DbContextOptions<AppDbContext>? ReplicaOptions => replica;
    public DbNodeMonitor Monitor => monitor;
}
