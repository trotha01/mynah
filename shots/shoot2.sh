#!/bin/zsh
# usage: shoot2.sh TAG WORKERS [extra]  -> shots/TAG-WxH.png
CH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
for sz in 1470x447 735x447; do "$CH" --headless=new --disable-gpu --hide-scrollbars --window-size=${sz/x/,} --virtual-time-budget=6000 --screenshot=$HOME/src/mynah/shots/$1-$sz.png "http://127.0.0.1:8861/?still=1&demo=speaking&workers=$2$3" >/dev/null 2>&1; done
