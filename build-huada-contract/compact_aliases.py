from pathlib import Path
p=Path('src/at_config.c')
s=p.read_text(encoding='utf-8')
a=s.index('    if (strcmp(cmd, "SOSALM")')
b=s.index('    /* AGPS=ON|OFF:',a)
s=s[:a]+r'''    /* Legacy acknowledgement-only aliases retain their original behavior. */
    static const char aliases[] = "SOSALM\0GMT\0CELLAUTOGMT\0GEOREP\0ANGLEREP\0MILEAGE\0AUTOAPN\0";
    for(const char *p=aliases;*p;p+=strlen(p)+1U) {
        if(!strcmp(cmd,p)){dbg_printf("OK\r\n");return;}
    }
    if(!strcmp(cmd,"SENDS") && argc>=1){dbg_printf("OK\r\n");return;}
'''+s[b:]
p.write_text(s,encoding='utf-8')
