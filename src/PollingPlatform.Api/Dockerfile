# Build context — корінь репозиторію (див. docker-compose.yml).

FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

# Спершу лише csproj — шар з restore кешується, поки не змінюються залежності.
COPY src/PollingPlatform.Api/PollingPlatform.Api.csproj src/PollingPlatform.Api/
RUN dotnet restore src/PollingPlatform.Api/PollingPlatform.Api.csproj

COPY src/ src/
RUN dotnet publish src/PollingPlatform.Api/PollingPlatform.Api.csproj -c Release -o /app/publish --no-restore /p:UseAppHost=false

# Інструменти профілювання (лаба 9, ADR 0067): CPU-профіль, лічильники GC / алокацій, знімок купи. Ставляться тут, бо в
# runtime-образі немає SDK; копіюються окремим шаром і запускаються через `docker compose exec backend-1 ...`.
RUN dotnet tool install --tool-path /tools dotnet-trace --version 10.0.750501 \
 && dotnet tool install --tool-path /tools dotnet-counters --version 10.0.750501 \
 && dotnet tool install --tool-path /tools dotnet-gcdump --version 10.0.750501

FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS runtime
WORKDIR /app
COPY --from=build /app/publish .
COPY --from=build /tools /tools
ENV PATH="$PATH:/tools"

ENV ASPNETCORE_HTTP_PORTS=8080
EXPOSE 8080

# Непривілейований користувач з базового образу.
USER $APP_UID
ENTRYPOINT ["dotnet", "PollingPlatform.Api.dll"]
