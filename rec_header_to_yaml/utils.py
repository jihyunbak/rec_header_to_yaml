# utils.py

import os
import io
import xmltodict
import json
import yaml

# from rec_to_nwb.processing.header.xml_extractor import XMLExtractor


def _copy_into(file, source_file):
    ''' append to file the entire contents of source_file '''
    fout = io.open(file, 'a') # always append
    with io.open(source_file, 'r') as fin:
        try:
            for line in fin:
                fout.write(line)
        except Exception as e: # catch *all* exceptions
            print(e)
            fout.close()

# --- copy rec header to a separate (xml) file

def read_rec_header(path, max_lines=1000, encoding='ISO-8859-1', stop_marker=None):
    header = []
    with io.open(path, 'r', encoding=encoding) as fh:
        try:
            cnt = 0
            for line in fh:
                header.append(line)
                cnt = cnt + 1
                stop = (cnt >= max_lines) or (stop_marker and stop_marker in line)
                if stop:
                    break
        except Exception as e: # catch *all* exceptions
            print('Error while reading line {}:'.format(cnt))
            print(e)
            fcopy.close()
            return None
    return header

def _copy_header_lines(rec_path=None, copy_path=None, encoding='ISO-8859-1',
                       stop_marker=None, max_lines=1000):
    if rec_path is None:
        raise ValueError('input path is required.')
    if copy_path is None:
        raise ValueError('output path is required.')
    fcopy = io.open(copy_path, 'w', encoding=encoding)
    with io.open(rec_path, 'r', encoding=encoding) as fh:
        try:
            cnt = 0
            for line in fh:
                fcopy.write(line)
                cnt = cnt + 1
                stop = (cnt >= max_lines) or (stop_marker and stop_marker in line)
                if stop:
                    break
        except Exception as e: # catch *all* exceptions
            print('Error while reading line {}:'.format(cnt))
            print(e)
            fcopy.close()
            return None
    fcopy.close()
    return cnt

def copy_rec_header(rec_path, copy_dir, max_lines=1000, talkative=False):
    # check input path
    rec_dir = os.path.dirname(rec_path)
    rec_filename = os.path.basename(rec_path)
    if rec_filename[-4:] != '.rec':
        raise ValueError('unknown file extension')
    if talkative:
        print('Input file: {}'.format(rec_path))
    
    # set output path
    os.makedirs(copy_dir, exist_ok=True)
    copy_path = os.path.join(copy_dir, 
                             rec_filename + '_header' + '.xml' # .rec_header.xml
                            )
    
    # copy line by line
    cnt = _copy_header_lines(rec_path=rec_path,
                             copy_path=copy_path,
                             encoding='ISO-8859-1',
                             stop_marker='</Configuration>',
                             max_lines=max_lines)
    # if talkative:
    #     print('Copied {} lines.'.format(cnt))
    
    # could also use rec_to_nwb (same output)
    # temp_xml_extractor = XMLExtractor(rec_path=rec_path, xml_path=copy_path)
    # temp_xml_extractor.extract_xml_from_rec_file()
    if talkative:
        print('Output file: {}'.format(copy_path))

def write_xml_from_list(out_filename, header):
    ''' not needed '''
    with open(out_filename, 'w') as fh:
        for line in header:
            fh.write('%s' % line) # line already includes '\n'

# --- header xml to dict

def read_xml(xml_path, attr_prefix='', unorder_dict=True):
    '''
    default attr_prefix for xmltodict is '@'
    '''
    with open(xml_path) as fh:
        ordered_dict = xmltodict.parse(fh.read(), attr_prefix=attr_prefix)
    if unorder_dict:
        # convert to plain dict
        return json.loads(json.dumps(ordered_dict))
    return ordered_dict

# --- dict helpers

def show_keys(dict_obj, depth=None, prefix='- ', indent='  '):
    if depth == 0:
        return
    for key, value in dict_obj.items():
        print(prefix + key)
        if not isinstance(value, dict):
            continue
        depth = depth - 1 if (depth is not None) else None
        show_keys(value, depth=depth, 
                  prefix=(indent + prefix), indent=indent)
    return

# --- yaml i/o

class MyDumper(yaml.Dumper):
    # ref: https://stackoverflow.com/a/39681672
    def increase_indent(self, flow=False, indentless=False):
        return super(MyDumper, self).increase_indent(flow, False)

def write_yml(yml_path, data, access_mode='w', default_flow_style=False, sort_keys=False):
    # note: additional kwargs may not work in older versions of pyyaml
    with io.open(yml_path, access_mode) as fh:
        yaml.dump(data, fh,
                  Dumper=MyDumper,
                  default_flow_style=default_flow_style,
                  sort_keys=sort_keys)
        
def append_yml(yml_path, data, **kwargs):
    write_yml(yml_path, data, access_mode='a', **kwargs)
        
def read_yml(yml_path):
    with io.open(yml_path, 'r') as fh:
        # data = yaml.load(fh, Loader=yaml.FullLoader)
        data = yaml.safe_load(fh) # always use safe_load
    return data
