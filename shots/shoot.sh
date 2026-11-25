#!/bin/zsh
# usage: shoot.sh TAG [extra query]  -> shots/TAG-WxH.png at three pane sizes
CH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
W="Saint%20videos:needs_you,Bokashi%20bin:blocked,J%20workers%20list:running,Typography:running,Comedy%20research:running,Cloud%20env:waiting"
for sz in 1470x447 735x447 500x700; do "$CH" --headless=new --disable-gpu --hide-scrollbars --window-size=${sz/x/,} --virtual-time-budget=6000 --screenshot=$HOME/src/mynah/shots/$1-$sz.png "http://127.0.0.1:8861/?still=1&demo=speaking&workers=$W$2" >/dev/null 2>&1; done
