-- Один запит каталогу на одному шарді (лаба 9): ті самі два оператори, що генерує EF для GET /api/polls?status=active.
SELECT count(*)::int FROM polls AS p WHERE p.is_public AND p.status <> 'draft' AND p.status = 'active';
SELECT p.id, p.title, p.status, p.is_public, p.creator_id, p.creator_username, (SELECT count(*)::int FROM options AS o WHERE p.id = o.poll_id), p.starts_at, p.ends_at, p.created_at FROM polls AS p WHERE p.is_public AND p.status <> 'draft' AND p.status = 'active' ORDER BY p.created_at DESC, p.id DESC LIMIT 20;
