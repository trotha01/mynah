# Todo headings run in Claude cloud (CLOUD_SESSION property): prints tag<TAB>updated<TAB>name for each open one.
# Reads ~/org/todo.org (kept current by Emacs, or by the todo database mirror).
function flush() {
  if (cloud && tag != "") { n = (short != "" ? short : title); gsub(/\t/, " ", n); print tag "\t" upd "\t" n }
  cloud = 0; tag = ""; short = ""; upd = ""; title = ""
}
/^\* / {
  flush()
  title = $0; sub(/^\* +(TODO|DONE|NEXT|WAIT) +/, "", title)
  if (match($0, /:[a-z_:]+: *$/)) {
    t = substr($0, RSTART, RLENGTH); gsub(/ /, "", t)
    m = split(t, parts, ":")
    for (i = 1; i <= m; i++) if (parts[i] ~ /^(needs_you|blocked|running|waiting)$/) tag = parts[i]
    sub(/ *:[a-z_:]+: *$/, "", title)
  }
  next
}
/^:SHORT: / { short = $0; sub(/^:SHORT: +/, "", short) }
/^:UPDATED: / { upd = $0; sub(/^:UPDATED: +/, "", upd) }
/^:CLOUD_SESSION: / { cloud = 1 }
END { flush() }
