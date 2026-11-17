#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check SPSS remoteproc links, reserved memory and suppliers in final DTBs."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from check_annibale_power_dt import enabled, require


def inspect(tree, cells):
    nodes = tree.nodes
    ph = {cells(p['phandle'])[0]: n for n, p in nodes.items() if 'phandle' in p}
    def one(compat):
        found = [n for n,p in nodes.items() if compat.encode() in p.get('compatible', b'').split(b'\0') and enabled(nodes,n)]
        require(len(found) == 1, 'expected one active ' + compat)
        return found[0]
    def refs(path, key, count_key=None):
        require(key in nodes[path], path + ': missing ' + key)
        values = cells(nodes[path][key]); result = []; index = 0
        while index < len(values):
            require(values[index] in ph, path + ': unresolved ' + key)
            supplier = ph[values[index]]
            require(enabled(nodes,supplier), path + ': disabled supplier ' + supplier)
            count = 0
            if count_key:
                require(count_key in nodes[supplier], supplier + ': missing ' + count_key)
                count_value = cells(nodes[supplier][count_key]);require(len(count_value)==1,'invalid provider cell count')
                count = count_value[0]
            require(index + 1 + count <= len(values), 'truncated ' + key)
            result.append({'provider':supplier,'args':values[index+1:index+1+count]});index += 1+count
        require(result, 'empty ' + key)
        return result
    def single(path,key):
        found=refs(path,key);require(len(found)==1,'expected one '+key);return found[0]['provider']
    remote = one('qcom,sun-spss-pas'); util=one('qcom,spss-utils'); comm=one('qcom,spcom')
    require(single(util,'qcom,rproc-handle') == single(comm,'qcom,rproc-handle') == remote, 'SPU clients reference different remoteproc')
    region=single(remote,'memory-region')
    require(single(util,'pil-mem') == region,'SPU clients use different reserved memory')
    require(region.startswith('/reserved-memory/') and 'no-map' in nodes[region], 'SPSS memory must be reserved no-map')
    parent=region.rsplit('/',1)[0]
    require(cells(nodes[parent].get('#address-cells', b''))==[2] and cells(nodes[parent].get('#size-cells',b''))==[2], 'expected 64-bit reserved memory layout')
    reg=cells(nodes[region].get('reg',b''));require(len(reg)==4,'expected single SPSS memory range')
    start=(reg[0]<<32)|reg[1];size=(reg[2]<<32)|reg[3]
    pil=cells(nodes[util].get('qcom,pil-size',b''));extra=cells(nodes[remote].get('qcom,extra-size',b''))
    require(len(pil)==len(extra)==1 and 0 < pil[0] and 0 < extra[0] and pil[0]+extra[0]<=size,'SPSS firmware/CMAC exceeds reserved memory')
    firmware={}
    for kind in ('dev','test','prod'):
        value=nodes[util].get('qcom,spss-'+kind+'-firmware-name',b'')
        expected={'dev':b'spss1d.mdt\0','test':b'spss1t.mdt\0','prod':b'spss1p.mdt\0'}[kind]
        require(value==expected,'unexpected SPSS firmware branch '+kind)
        firmware[kind]=value[:-1].decode()
    require(nodes[comm].get('qcom,spcom-ch-names')==b'sp_kernel\0sp_ssr\0','unexpected SPU control channels')
    require('qcom,boot-enabled' in nodes[comm],'SPU userspace boot control absent')
    require(cells(nodes[remote].get('qcom,spss-scsr-bits',b''))==[24,25],'unexpected SPSS status bits')
    edge=remote+'/glink-edge';require(edge in nodes and enabled(nodes,edge),'missing active SPSS GLINK edge')
    require(cells(nodes[edge].get('qcom,remote-pid',b''))==[8],'unexpected SPSS remote PID')
    suppliers={key:refs(remote,key,count) for key,count in {'cx-supply':None,'sensors-supply':None,'qcom,qmp':None,'clocks':'#clock-cells','interconnects':'#interconnect-cells'}.items()}
    suppliers['glink-mboxes']=refs(edge,'mboxes','#mbox-cells')
    suppliers['glink-interrupt-parent']=refs(edge,'interrupt-parent')
    require(len(suppliers['clocks'])==1 and len(suppliers['interconnects'])==2,'SPSS clock/interconnect endpoint count changed')
    require(len(suppliers['glink-mboxes'])==1 and suppliers['glink-mboxes'][0]['provider']==suppliers['glink-interrupt-parent'][0]['provider'],'SPSS GLINK mailbox and IRQ provider mismatch')
    return {'remoteproc':remote,'utils':util,'communication':comm,'memory':{'path':region,'start':start,'size':size,'pil_size':pil[0],'extra_size':extra[0]},'firmware_names':firmware,'suppliers':suppliers}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--devicetrees',type=Path,required=True);ap.add_argument('--dt-images',type=Path,required=True);ap.add_argument('--report',type=Path,required=True)
    args=ap.parse_args();sys.path.insert(0,str(args.devicetrees/'tools'))
    from annibale_fdt import Fdt,cells
    results={}
    for family in ('tfa','sia'):
        for mode in ('default','native'):
            for base in ('sun','sun-v2','sun-tp','sun-tp-v2','sunp','sunp-v2','sunp-tp','sunp-tp-v2'):
                relative=f'{family}-{mode}/{base}.dtb';data=(args.dt_images/relative).read_bytes()
                result=inspect(Fdt(data),cells);result['sha256']=hashlib.sha256(data).hexdigest();results[relative]=result
    args.report.write_text(json.dumps({'status':'spu_dt_passed','hardware_verified':False,'firmware_verified':False,'dtbs':results},indent=2)+'\n')
    print(f'PASS: {len(results)} SPSS DT bindings; firmware and hardware unverified')


if __name__=='__main__':
    main()
