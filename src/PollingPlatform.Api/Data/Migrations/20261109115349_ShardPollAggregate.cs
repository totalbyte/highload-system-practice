using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

#nullable disable

namespace PollingPlatform.Api.Data.Migrations
{
    /// <inheritdoc />
    public partial class ShardPollAggregate : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropForeignKey(
                name: "fk_polls_users_creator_id",
                table: "polls");

            migrationBuilder.DropForeignKey(
                name: "fk_votes_users_user_id",
                table: "votes");

            migrationBuilder.DropIndex(
                name: "ix_votes_user_id",
                table: "votes");

            migrationBuilder.CreateSequence(
                name: "poll_ids");

            migrationBuilder.AlterColumn<long>(
                name: "id",
                table: "polls",
                type: "bigint",
                nullable: false,
                oldClrType: typeof(long),
                oldType: "bigint")
                .OldAnnotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn);

            migrationBuilder.AddColumn<string>(
                name: "creator_username",
                table: "polls",
                type: "character varying(50)",
                maxLength: 50,
                nullable: false,
                defaultValue: "");

            // На томі з даними до лаби 7: ім'я автора з users і послідовність після найбільшого id. Самі опитування при цьому
            // лишаються на Shard A, а роутер шукатиме частину з них на Shard B, тож для лаби 7 потрібен `docker compose down -v`.
            migrationBuilder.Sql("UPDATE polls p SET creator_username = u.username FROM users u WHERE u.id = p.creator_id;");
            migrationBuilder.Sql("SELECT setval('poll_ids', COALESCE((SELECT max(id) FROM polls), 0) + 1, false);");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "creator_username",
                table: "polls");

            migrationBuilder.DropSequence(
                name: "poll_ids");

            migrationBuilder.AlterColumn<long>(
                name: "id",
                table: "polls",
                type: "bigint",
                nullable: false,
                oldClrType: typeof(long),
                oldType: "bigint")
                .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn);

            migrationBuilder.CreateIndex(
                name: "ix_votes_user_id",
                table: "votes",
                column: "user_id");

            migrationBuilder.AddForeignKey(
                name: "fk_polls_users_creator_id",
                table: "polls",
                column: "creator_id",
                principalTable: "users",
                principalColumn: "id",
                onDelete: ReferentialAction.Restrict);

            migrationBuilder.AddForeignKey(
                name: "fk_votes_users_user_id",
                table: "votes",
                column: "user_id",
                principalTable: "users",
                principalColumn: "id",
                onDelete: ReferentialAction.Restrict);
        }
    }
}
