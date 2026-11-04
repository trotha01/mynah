;;;; companion: J, the voice-mode character shown in a Jmacs web pane.
;;;; sbcl --script companion.lisp [port]     (default 8860, bound to 127.0.0.1)
;;;;   GET /          index.html (read from this directory on every request)
;;;;   GET /api/s     {"state":"...","level":0.0-..,"on":true|false,"q":true|false}  (q: the reply being spoken ends in "?")
;;;; state = "off" when the mode file ~/.config/jmacs/voice-conversation is absent (MYNAH_VOICE_MODE_FILE), "loading" when
;;;; it is present but speakd is not running, else the voice loop's state file (loading listening hearing transcribing
;;;; waiting speaking); level = RMS of the audio speakd is playing right now
;;;; (voice-level, 0 when stale). Read-only: it never touches the voice-mode switch.
;;;; Worker announcements: a background thread polls todoview (the todo list page, GET /api/items) for workers whose
;;;; status tag changes to waiting / done / needs_you / blocked, and shows each as a note on /api/s ("note":{n,text,kind,age}).
;;;; With voice mode on it also speaks one short line ("Saint videos is waiting for you") by writing a .say file into the
;;;; speaker's inbox, but only when nothing else is going on: state listening for 2.5 s, no level, nothing queued in the
;;;; inbox, 3 s since the last announcement. Pending lines are grouped, dropped after 90 s, and never queued while voice
;;;; mode is off. Debounce: the same worker and tag within 90 s is ignored; the orchestrator (win "left...") is skipped.
;;;; Env: COMPANION_TODOVIEW (default http://127.0.0.1:8850), MYNAH_INBOX, MYNAH_VOICE_STATE_FILE, MYNAH_LEVEL_FILE, MYNAH_PID_FILE (all under ~/.local/state/mynah by default).

(require :sb-bsd-sockets)
(require :sb-posix)
(defpackage :companion (:use :cl :sb-bsd-sockets))
(in-package :companion)

(defparameter *dir* (directory-namestring (or *load-truename* *default-pathname-defaults*)))
(defun env (name default) (let ((v (sb-posix:getenv name))) (if (and v (string/= v "")) v default)))
(defun state-path (name) (namestring (merge-pathnames (format nil ".local/state/mynah/~a" name) (user-homedir-pathname))))
(defparameter *state-file* (env "MYNAH_VOICE_STATE_FILE" (state-path "voice-state")))
(defparameter *level-file* (env "MYNAH_LEVEL_FILE" (state-path "voice-level")))
(defparameter *mode-file* (env "MYNAH_VOICE_MODE_FILE" (namestring (merge-pathnames ".config/jmacs/voice-conversation" (user-homedir-pathname)))))
(defvar *last-state* "listening")
(defparameter *kind-file* (env "MYNAH_SAY_KIND_FILE" (state-path "voice-say-kind")))
(defparameter *todoview* (env "COMPANION_TODOVIEW" "http://127.0.0.1:8850"))
(defparameter *inbox* (env "MYNAH_INBOX" (state-path "inbox")))
(defparameter *pid-file* (env "MYNAH_PID_FILE" (state-path "speakd.pid")))

(defun log-line (fmt &rest args) (format t "~&companion: ~?~%" fmt args) (finish-output))
(defun prefix-p (prefix s) (and (>= (length s) (length prefix)) (string= prefix s :end2 (length prefix))))

(defun first-line (path)
  (ignore-errors (with-open-file (in path :external-format :utf-8)
                   (string-trim '(#\Space #\Tab #\Return) (or (read-line in nil) "")))))

(defun now ()
  (multiple-value-bind (sec usec) (sb-ext:get-time-of-day) (+ sec (/ usec 1d6))))

(defun read-level ()
  "The voice-level file is \"<rms> <unix time>\"; 0 when missing or older than 0.35 s."
  (or (ignore-errors
       (let* ((s (first-line *level-file*)) (sp (position #\Space s))
              (*read-default-float-format* 'double-float)
              (rms (read-from-string (subseq s 0 sp))) (ts (read-from-string (subseq s (1+ sp)))))
         (and (realp rms) (realp ts) (< (- (now) ts) 0.35) rms)))
      0))

(defun alive-p ()
  (let* ((s (first-line *pid-file*)) (pid (and s (ignore-errors (parse-integer s)))))
    (and pid (ignore-errors (zerop (sb-posix:kill pid 0))))))

(defun valid-state-p (s) (and s (plusp (length s)) (every (lambda (c) (or (alpha-char-p c) (char= c #\-))) s)))

(defun mode-on-p () (and (probe-file *mode-file*) t))

(defun current-state ()
  "Voice mode on/off is the mode file (what `voice-mode status` reports), not the speaker's pid or a state-file
read: listen.py rewrites the state file in place, so a read can see it empty, and the speaker restarts. With the
mode on, a bad read keeps the last good state and a missing speaker means it is waking up."
  (if (not (mode-on-p))
      (progn (setf *last-state* "listening") "off")
      (let ((st (first-line *state-file*)))
        (cond ((not (alive-p)) "loading")
              ((and (valid-state-p st) (string/= st "off")) (setf *last-state* st))
              (t *last-state*)))))

(defun api-state ()
  (let ((state (current-state)) (level (read-level)))
    (format nil "{\"state\":\"~a\",\"level\":~,4f,\"on\":~a,\"q\":~a,\"note\":~a}" state (min 1 level) (if (mode-on-p) "true" "false")
            (if (equal (first-line *kind-file*) "question") "true" "false") (note-json))))


;;; Worker announcements

(defparameter *announce-tags* '("waiting" "done" "needs_you" "blocked"))
(defvar *seen* (make-hash-table :test 'equal))      ; win -> (tag . updated)
(defvar *last-said* (make-hash-table :test 'equal)) ; (win . tag) -> unix time (debounce)
(defvar *baseline* t)                               ; the first poll only records, it never announces
(defvar *pending* nil)                              ; (name kind time), to be spoken
(defvar *note* nil)                                 ; (n text kind time) for the page
(defvar *note-n* 0)
(defvar *quiet-since* nil)
(defvar *last-spoken* 0)

(defun split-tabs (s) (loop for start = 0 then (1+ end) for end = (position #\Tab s :start start)
                            collect (subseq s start end) while end))

(defun json-escape (s)
  (with-output-to-string (o)
    (loop for c across s do (case c (#\" (write-string "\\\"" o)) (#\\ (write-string "\\\\" o))
                              (t (if (< (char-code c) 32) (write-char #\Space o) (write-char c o)))))))

(defun fetch-workers ()
  "List of (win tag updated name) for every todo heading that has a window and a status tag, via todoview + jq."
  (ignore-errors
   (let ((out (with-output-to-string (o)
                (sb-ext:run-program "/bin/sh"
                                    (list "-c" (format nil "curl -s -m 2 ~a/api/items | jq -r '.items[] | select(.win!=\"\" and .tag!=\"\") | [.win,.tag,.updated,((.short|select(.!=\"\"))//.title|gsub(\"[\\t\\n]\";\" \"))]|@tsv'" *todoview*))
                                    :search t :output o :error nil :environment (cons "PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin" nil)))))
     (loop for line in (let ((acc nil)) (with-input-from-string (i out) (loop for l = (read-line i nil) while l do (push l acc))) (nreverse acc))
           for f = (split-tabs line)
           when (= (length f) 4) collect f))))

(defun announce-line (name kind)
  (cond ((string= kind "waiting") (format nil "~a is waiting for you" name))
        ((string= kind "needs_you") (format nil "~a needs you" name))
        ((string= kind "done") (format nil "~a is done" name))
        (t (format nil "~a is blocked" name))))

(defun announce-many (names kind)
  "NAMES (2 or more) in one line: \"A and B are waiting for you\"."
  (let ((tail (cond ((string= kind "waiting") "are waiting for you") ((string= kind "needs_you") "need you")
                    ((string= kind "done") "are done") (t "are blocked"))))
    (if (<= (length names) 3)
        (format nil "~{~a~^, ~} and ~a ~a" (butlast names) (car (last names)) tail)
        (format nil "~d sessions ~a" (length names) tail))))

(defun note! (text kind)
  (setf *note* (list (incf *note-n*) text kind (now))))

(defun detect-changes (rows)
  (let ((pending-before (length *pending*)))
    (declare (ignorable pending-before))
    (dolist (r rows)
      (destructuring-bind (win tag updated name) r
        (let ((prev (gethash win *seen*)))
          (setf (gethash win *seen*) (cons tag updated))
          (when (and (not *baseline*) (not (prefix-p "left" win))
                     (member tag *announce-tags* :test #'string=)
                     (or (null prev) (string/= (car prev) tag) (string/= (cdr prev) updated))
                     (or (null prev) (string/= (car prev) tag))
                     (let ((last (gethash (cons win tag) *last-said*))) (or (null last) (> (- (now) last) 90))))
            (setf (gethash (cons win tag) *last-said*) (now))
            (note! (announce-line name tag) tag)
            (when (mode-on-p) (push (list name tag (now)) *pending*))))))
    (setf *baseline* nil)))

(defun inbox-busy-p ()
  (ignore-errors (some (lambda (p) (member (pathname-type p) '("say" "stop") :test #'string=))
                       (directory (merge-pathnames "*.*" (concatenate 'string (string-right-trim "/" *inbox*) "/"))))))

(defun compose (items)
  "One short spoken line: workers grouped by what they need (\"A and B are waiting for you. C is done\")."
  (let ((parts nil))
    (dolist (kind '("needs_you" "waiting" "blocked" "done"))
      (let ((names (reverse (loop for (n k) in items when (string= k kind) collect n))))
        (when names
          (push (if (= (length names) 1) (announce-line (first names) kind) (announce-many names kind)) parts))))
    (format nil "~{~a.~^ ~}" (nreverse parts))))

(defun speak-line (text)
  (let* ((dir (concatenate 'string (string-right-trim "/" *inbox*) "/")) (n (format nil "~15,3,,,'0f.~d" (now) (sb-posix:getpid)))
         (tmp (format nil "~a.~a.tmp" dir n)) (final (format nil "~a~a.say" dir n)))
    (ensure-directories-exist dir)
    (with-open-file (o tmp :direction :output :if-exists :supersede :external-format :utf-8) (write-line text o))
    (rename-file tmp final)))

(defun maybe-speak ()
  (setf *pending* (remove-if (lambda (p) (> (- (now) (third p)) 90)) *pending*))
  (when (not (mode-on-p)) (setf *pending* nil))
  (let ((quiet (and (mode-on-p) (alive-p) (equal (first-line *state-file*) "listening") (< (read-level) .005))))
    (if quiet (unless *quiet-since* (setf *quiet-since* (now))) (setf *quiet-since* nil))
    (when (and *pending* *quiet-since* (> (- (now) *quiet-since*) 2.5) (> (- (now) *last-spoken*) 3) (not (inbox-busy-p)))
      (let ((text (compose *pending*)))
        (setf *pending* nil *last-spoken* (now))
        (log-line "announce: ~a" text)
        (speak-line text)))))

(defun watcher ()
  (let ((tick 0))
    (loop
      (handler-case
          (progn (when (zerop (mod tick 3)) (let ((rows (fetch-workers))) (when rows (detect-changes rows))))
                 (maybe-speak))
        (error (e) (log-line "watcher error: ~a" e)))
      (incf tick) (sleep 1))))

(defun note-json ()
  (if (and *note* (< (- (now) (fourth *note*)) 30))
      (format nil "{\"n\":~d,\"text\":\"~a\",\"kind\":\"~a\",\"age\":~,1f}" (first *note*) (json-escape (second *note*)) (third *note*) (- (now) (fourth *note*)))
      "null"))

(defun read-line-bytes (stream)
  (string-right-trim '(#\Return)
                     (map 'string #'code-char
                          (loop for b = (read-byte stream nil) until (or (null b) (= b 10)) collect b))))

(defun send (stream status type body)
  (let ((bytes (if (stringp body) (sb-ext:string-to-octets body :external-format :utf-8) body)))
    (write-sequence (sb-ext:string-to-octets
                     (format nil "HTTP/1.0 ~a~c~cContent-Type: ~a~c~cContent-Length: ~d~c~cCache-Control: no-store~c~c~c~c"
                             status #\Return #\Newline type #\Return #\Newline (length bytes) #\Return #\Newline
                             #\Return #\Newline #\Return #\Newline))
                    stream)
    (write-sequence bytes stream)
    (finish-output stream)))

(defun file-bytes (p)
  (with-open-file (in p :element-type '(unsigned-byte 8))
    (let ((v (make-array (file-length in) :element-type '(unsigned-byte 8)))) (read-sequence v in) v)))

(defun handle (stream)
  (let* ((line (read-line-bytes stream))
         (sp (position #\Space line))
         (path (if sp (subseq line (1+ sp) (position #\Space line :start (1+ sp))) "/")))
    (loop for h = (read-line-bytes stream) until (string= h ""))
    (cond ((prefix-p "/health" path) (send stream "200 OK" "text/plain" "ok"))
          ((prefix-p "/api/s" path) (send stream "200 OK" "application/json" (api-state)))
          (t (send stream "200 OK" "text/html; charset=utf-8" (file-bytes (merge-pathnames "index.html" *dir*)))))))

(defun listener (port)
  (let ((sock (make-instance 'inet-socket :type :stream :protocol :tcp)))
    (setf (sockopt-reuse-address sock) t)
    (unwind-protect
         (progn
           (socket-bind sock #(127 0 0 1) port)
           (socket-listen sock 64)
           (log-line "J on http://127.0.0.1:~d/" port)
           (loop
             (let ((client (socket-accept sock)))
               (sb-thread:make-thread
                (lambda ()
                  (unwind-protect
                       (handler-case
                           (handle (socket-make-stream client :input t :output t
                                                              :element-type '(unsigned-byte 8) :buffering :full))
                         (error (e) (log-line "request error: ~a" e)))
                    (socket-close client)))))))
      (socket-close sock))))

(sb-thread:make-thread #'watcher :name "watcher")

(let ((port (parse-integer (or (second sb-ext:*posix-argv*) "8860"))))
  (loop (handler-case (listener port)
          (error (e) (log-line "listener crashed: ~a" e) (sleep 1)))))
