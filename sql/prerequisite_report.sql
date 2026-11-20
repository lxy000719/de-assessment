SELECT
e.participant_id,
e.participant_name,
e.course_id,
c.name AS course_name,
e.course_date,
CAST(p.value AS INTEGER) AS prerequisite_course_id,
pc.name AS prerequisite_course_name

FROM enrollments e
JOIN courses c ON e.course_id = c.course_id
JOIN json_each(c.prerequisites) p
LEFT JOIN courses pc ON pc.course_id = CAST(p.value AS INTEGER)
LEFT JOIN enrollments pe ON pe.participant_id = e.participant_id
AND pe.course_id = CAST(p.value AS INTEGER)
AND pe.course_date < e.course_date

WHERE pe.enrollment_id IS NULL

ORDER BY
e.participant_id,
e.course_date,
prerequisite_course_id;