;;;; Voice memory and latency, before / after a change. Read-only: it only runs `ps` (and `footprint` when macOS has it)
;;;; and reads the speakd log. It never starts, stops or touches any voice process.
;;;;   sbcl --script tools/voice-measure.lisp [LOGFILE [N]]
;;;; LOGFILE defaults to ~/Library/Logs/mynah-speakd.log (what hooks/claude-speak writes), N (default 20) is how many of
;;;; the newest matching log lines count. Run it with voice mode OFF for the resident baseline, once more after a reply
;;;; has been spoken, and (Trevor, voice mode on) once during a conversation. Details: docs/voice-memory.md.

(defparameter *patterns*   ; (substring of the ps command line . label)
  '(("mynah.speakd" . "speakd (Kokoro TTS + listener: Parakeet, Silero, speaker-id, AEC; one process)")
    ("mynah.main" . "mynah hotkey app (separate Kokoro load if used)")
    ("bin/mynah" . "mynah hotkey app (separate Kokoro load if used)")
    ("Mynah Speaker" . "launcher app (should exit right after starting speakd)")
    ("companion.lisp" . "companion page (sbcl, port 8860)")))

(defun run (program &rest args)
  "Output of PROGRAM as a list of lines; NIL when it cannot be run."
  (handler-case
      (with-output-to-string (s)
        (sb-ext:run-program program args :search t :output s :error nil :input nil))
    (error () nil)))

(defun lines (string)
  (loop with start = 0
        for nl = (position #\Newline string :start start)
        collect (subseq string start nl)
        while nl do (setf start (1+ nl))))

(defun has (needle hay) (search needle hay))

(defun number-after (marker line)
  "The non-negative decimal number right after MARKER in LINE, or NIL."
  (let ((p (search marker line)))
    (when p
      (let* ((s (+ p (length marker)))
             (e (or (position-if-not (lambda (c) (or (digit-char-p c) (char= c #\.))) line :start s) (length line)))
             (txt (subseq line s e))
             (dot (position #\. txt)))
        (when (plusp (length txt))
          (handler-case
              (if dot
                  (+ (if (zerop dot) 0 (parse-integer txt :end dot))
                     (let ((frac (subseq txt (1+ dot))))
                       (if (zerop (length frac)) 0 (/ (parse-integer frac) (expt 10 (length frac))))))
                  (parse-integer txt))
            (error () nil)))))))

(defun median (xs)
  (let* ((v (sort (copy-list xs) #'<)) (n (length v)))
    (when v (if (oddp n) (nth (floor n 2) v) (/ (+ (nth (1- (floor n 2)) v) (nth (floor n 2) v)) 2)))))

(defun f (x digits) (format nil "~,vF" digits (float x)))

(defun report-memory ()
  (format t "== resident memory (ps RSS; macOS leaves out compressed and swapped pages, so see Footprint too) ==~%")
  (let ((total 0) (found nil) (me (format nil "~a" (sb-unix:unix-getpid))))
    (dolist (line (lines (or (run "ps" "-axo" "pid=,rss=,command=") "")))
      (let* ((l (string-left-trim " " line))
             (sp1 (position #\Space l)))
        (when sp1
          (let* ((pid (subseq l 0 sp1))
                 (rest (string-left-trim " " (subseq l sp1)))
                 (sp2 (position #\Space rest))
                 (rss (and sp2 (ignore-errors (parse-integer rest :end sp2))))
                 (cmd (and sp2 (string-left-trim " " (subseq rest sp2))))
                 (hit (and cmd (not (string= pid me)) (not (has "voice-measure" cmd))
                           (find-if (lambda (p) (has (car p) cmd)) *patterns*))))
            (when hit
              (setf found t)
              (incf total (/ rss 1024.0))
              (format t "~8a ~8a MB  ~a~a~%" pid (f (/ rss 1024.0) 1) (cdr hit)
                      (if (has "--sleep" cmd) " [ASLEEP: models unloaded]" ""))
              (let ((fp (find-if (lambda (x) (has "Footprint:" x)) (lines (or (run "footprint" "-p" pid) "")))))
                (when fp (format t "         ~a~%" (string-trim " " fp)))))))))
    (if found
        (format t "~8a ~8a MB  total of the above~%" "" (f total 1))
        (format t "no voice process running (speakd starts on the next reply, or: hooks/claude-speak Start)~%"))))

(defun tail-lines (path n marker)
  "The last N lines of PATH containing MARKER (oldest first)."
  (let ((hits '()))
    (handler-case
        (with-open-file (in path :external-format :latin-1)
          (loop for line = (read-line in nil) while line
                do (when (has marker line) (push line hits))))
      (error () (return-from tail-lines :unreadable)))
    (reverse (subseq hits 0 (min n (length hits))))))

(defun series (path n marker unit-marker label)
  (let ((ls (tail-lines path n marker)))
    (cond ((eq ls :unreadable) (format t "~a: cannot read ~a~%" label path))
          ((null ls) (format t "~a: none in the log yet~%" label))
          (t (let ((xs (remove nil (mapcar (lambda (l) (number-after unit-marker l)) ls))))
               (format t "~a: n=~d  newest ~a  median ~a  max ~a~%" label (length xs)
                       (f (car (last xs)) 2) (f (median xs) 2) (f (reduce #'max xs) 2)))))))

(defun report-logs (path n)
  (format t "~%== speakd log: ~a (newest ~d matches) ==~%" path n)
  (series path n "first audio queued after" "first audio queued after " "time to first audio, s (generation start -> first chunk queued)")
  (series path n "transcribed in" "transcribed in " "transcription, s (end of utterance -> text)")
  (series path n "Voice models ready in" "Voice models ready in " "voice-mode-on model load, s")
  (series path n "Warm-up done in" "Warm-up done in " "Kokoro warm-up after (re)start, s")
  (let ((ls (tail-lines path 100000 "weights had been paged out")))
    (format t "page-out stalls logged (warm-up > 1.5 s): ~a~%" (if (eq ls :unreadable) "?" (length ls)))
    (when (and (listp ls) ls)
      (format t "  newest: ~a~%" (string-trim " " (car (last ls)))))))

(let* ((args (cdr sb-ext:*posix-argv*))
       (log (or (first args) (namestring (merge-pathnames "Library/Logs/mynah-speakd.log" (user-homedir-pathname)))))
       (n (or (and (second args) (ignore-errors (parse-integer (second args)))) 20)))
  (format t "voice-measure ~a~%~%" (multiple-value-bind (s m h d mo y) (get-decoded-time)
                                      (format nil "~4,'0d-~2,'0d-~2,'0d ~2,'0d:~2,'0d:~2,'0d" y mo d h m s)))
  (report-memory)
  (report-logs log n))
