;;;; companion: J, the voice-mode character shown in a Jmacs web pane.
;;;; sbcl --script companion.lisp [port]     (default 8860, bound to 127.0.0.1)
;;;;   GET /          index.html (read from this directory on every request)
;;;;   GET /api/s     {"state":"...","level":0.0-..,"alive":true|false}
;;;; state = "off" when the mode file ~/.config/jmacs/voice-conversation is absent (MYNAH_VOICE_MODE_FILE), "loading" when
;;;; it is present but speakd is not running, else the voice loop's state file (loading listening hearing transcribing
;;;; waiting speaking); level = RMS of the audio speakd is playing right now
;;;; (voice-level, 0 when stale). Read-only: it never touches the voice-mode switch.
;;;; Env: MYNAH_VOICE_STATE_FILE, MYNAH_LEVEL_FILE, MYNAH_PID_FILE (all under ~/.local/state/mynah by default).

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
    (format nil "{\"state\":\"~a\",\"level\":~,4f,\"on\":~a}" state (min 1 level) (if (mode-on-p) "true" "false"))))

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

(let ((port (parse-integer (or (second sb-ext:*posix-argv*) "8860"))))
  (loop (handler-case (listener port)
          (error (e) (log-line "listener crashed: ~a" e) (sleep 1)))))
