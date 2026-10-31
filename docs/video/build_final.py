import json, re, subprocess
V="/workspace/work/terms-desk/docs/video/terms-desk-demo.mp4"
marks=[0.1,7.9,22.0,35.4,51.3,72.1,101.2,112.6,120.4]
dur=[6.217,12.957,8.908,14.942,22.178,18.704,7.367,3.605]
LEAD=0.3; TAIL=[0.5,0.5,0.6,0.5,0.5,0.6,0.6,1.5]
words=json.load(open("words.json"))
FIX=[(r"\bterms desk\b","Terms Desk"),(r"\bskeptic\b","Skeptic"),(r"\brun agent\b","Run agent"),
     (r"\binvoicing\b","Invoicing"),(r"slow pair","slow payer"),(r"early payment","early-payment"),
     (r"One click and","One click, and"),(r"money built","money, built"),(r"payment, \$","payment: $")]
segs=[];audio=[];t=0.0;caps=[]
for i in range(8):
    win=marks[i+1]-marks[i]; L=LEAD+dur[i]+TAIL[i]
    take=min(L,win); pad=max(0,L-win)
    segs.append((marks[i],take,pad)); a0=t+LEAD; audio.append(a0)
    # merge tokens
    toks=[]
    for w,s,e in words[str(i+1)]:
        if toks and (w in ("%",) or w.startswith((",", "-", "%")) or w=="'s"):
            toks[-1]=[toks[-1][0]+w,toks[-1][1],e]
        else: toks.append([w,s,e])
    # chunk
    cur=[]
    def flush():
        if cur:
            txt=" ".join(x[0] for x in cur)
            caps.append([a0+cur[0][1],a0+cur[-1][2],txt]); cur.clear()
    for tk in toks:
        cur.append(tk)
        n=len(" ".join(x[0] for x in cur))
        if tk[0][-1] in ".!?" or (tk[0][-1] in ",:" and n>18) or n>38: flush()
    flush()
    t+=L
total=t
m=[]
for c in caps:
    if m and len(c[2])<10 and len(m[-1][2])+len(c[2])<=52 and c[0]-m[-1][1]<0.4:
        m[-1]=[m[-1][0],c[1],m[-1][2]+" "+c[2]]
    else: m.append(c)
caps=m
# fix text across whole caption (case-insensitive), and extend end to next start (no flicker)
for k,c in enumerate(caps):
    s=c[2]
    for a,b in FIX: s=re.sub(a,b,s,flags=re.I)
    c[2]=s.replace("$1,960 marked","$1,960, marked").replace("payment,","payment:").replace("$130, blocked.","$130. Blocked.")
    nxt=caps[k+1][0] if k+1<len(caps) else c[1]+0.8
    c[1]=min(max(c[1]+0.25,c[1]), nxt-0.02) if nxt-c[1]<0.6 else c[1]+0.25
def ts(x,ass=True):
    h=int(x//3600);m=int(x%3600//60);s=x%60
    return f"{h}:{m:02d}:{s:05.2f}" if ass else f"{h:02d}:{m:02d}:{int(s):02d},{int(round((s-int(s))*1000)):03d}".replace(",1000",",999")
ass=["[Script Info]","ScriptType: v4.00+","PlayResX: 1920","PlayResY: 1080","WrapStyle: 0","",
"[V4+ Styles]","Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
"Style: Cap,Inter Cap,50,&H00FFFFFF,&H00FFFFFF,&H00141414,&H96101010,0,0,0,0,100,100,0,0,3,18,0,2,200,200,64,1","",
"[Events]","Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
srt=[]
for k,(s,e,txt) in enumerate(caps):
    ass.append(f"Dialogue: 0,{ts(s)},{ts(e)},Cap,,0,0,0,,{{\\fad(60,60)}}{txt}")
    srt+= [str(k+1), f"{ts(s,False)} --> {ts(e,False)}", txt, ""]
open("caps.ass","w").write("\n".join(ass)+"\n"); open("captions.srt","w").write("\n".join(srt))
# ffmpeg graph
inp=["-i",V]+sum([["-i",f"{i}.mp3"] for i in range(1,9)],[])
f=[]
for k,(st,take,pad) in enumerate(segs):
    p=f",tpad=stop_mode=clone:stop_duration={pad:.2f}" if pad>0 else ""
    f.append(f"[0:v]trim=start={st}:duration={take},setpts=PTS-STARTPTS{p}[v{k}]")
f.append("".join(f"[v{k}]" for k in range(8))+"concat=n=8:v=1:a=0,ass=caps.ass:fontsdir=fonts[v]")
for k in range(8):
    d=int(audio[k]*1000); f.append(f"[{k+1}:a]aresample=48000,adelay={d}|{d}[a{k}]")
f.append("".join(f"[a{k}]" for k in range(8))+f"amix=inputs=8:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,apad,atrim=0:{total:.2f}[a]")
out="/workspace/work/terms-desk/docs/video/terms-desk-demo-final.mp4"
cmd=["ffmpeg","-y","-v","error"]+inp+["-filter_complex",";".join(f),"-map","[v]","-map","[a]","-c:v","libx264","-preset","medium","-crf","20","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-movflags","+faststart",out]
subprocess.run(cmd,check=True)
print("total",round(total,1),"captions",len(caps)); print([round(a,1) for a in audio])
for c in caps: print(round(c[0],2),round(c[1],2),c[2])
