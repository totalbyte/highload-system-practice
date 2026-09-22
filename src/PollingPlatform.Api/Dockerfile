# Build context — корінь репозиторію (див. docker-compose.yml).

FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

# Спершу лише csproj — шар з restore кешується, поки не змінюються залежності.
COPY src/PollingPlatform.Api/PollingPlatform.Api.csproj src/PollingPlatform.Api/
RUN dotnet restore src/PollingPlatform.Api/PollingPlatform.Api.csproj

COPY src/ src/
RUN dotnet publish src/PollingPlatform.Api/PollingPlatform.Api.csproj -c Release -o /app/publish --no-restore /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS runtime
WORKDIR /app
COPY --from=build /app/publish .

ENV ASPNETCORE_HTTP_PORTS=8080
EXPOSE 8080

# Непривілейований користувач з базового образу.
USER $APP_UID
ENTRYPOINT ["dotnet", "PollingPlatform.Api.dll"]
