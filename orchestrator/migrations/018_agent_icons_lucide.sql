-- Migrate existing emoji agent icons to lucide-react icon names.
-- Assigns icons round-robin so each icon is used at most once before repeating.
UPDATE agents SET icon = CASE
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 0) THEN 'Bot'
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 1) THEN 'BrainCircuit'
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 2) THEN 'Cpu'
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 3) THEN 'Radar'
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 4) THEN 'Orbit'
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 5) THEN 'Zap'
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 6) THEN 'Shield'
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 7) THEN 'Microscope'
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 8) THEN 'Compass'
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 9) THEN 'Anchor'
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 10) THEN 'Flame'
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 11) THEN 'Gem'
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 12) THEN 'Hexagon'
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 13) THEN 'Aperture'
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 14) THEN 'Atom'
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 15) THEN 'Fingerprint'
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 16) THEN 'Podcast'
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 17) THEN 'Satellite'
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 18) THEN 'Swords'
    WHEN rowid IN (SELECT rowid FROM agents WHERE status = 'active' ORDER BY created_at LIMIT 1 OFFSET 19) THEN 'TreePine'
    ELSE 'Bot'
END
WHERE icon NOT IN ('Bot','BrainCircuit','Cpu','Radar','Orbit','Zap','Shield','Microscope','Compass','Anchor','Flame','Gem','Hexagon','Aperture','Atom','Fingerprint','Podcast','Satellite','Swords','TreePine');
