# metadata.py

import os
import io
from pathlib import Path
import re
import parse

from .utils import copy_rec_header, read_xml, append_yml


HOME_DIR = os.path.expanduser('~')
DEFAULT_TEMP_DIR = os.path.join(HOME_DIR, 'tmp/rec_header/')


class NWBMetadataHelper():
    ''' help collecting metadata.yaml from experimental output. '''

    def __init__(self,
                 data_path: str,
                 animal_name: str,
                 date: str,
                 dio_id: dict,
                 experimenter_name=None,
                 experiment_description=None,
                 session_description=None,
                 animal_nickname=None,
                 subject_info: dict = dict(),
                 placeholder_text: str = 'Unknown',
                 copy_path: str = DEFAULT_TEMP_DIR,
                 reconfig=None,
                 task_code=None,
                 filename_format=None,
                 **kwargs):
        self.animal_name = animal_name
        self.date = date
        self.data_path = data_path
        # animal_nickname: for file naming only (animal_name for folder naming)
        # (if the two are different)
        self.animal_nickname = animal_nickname or self.animal_name
        self.session_id = '{}_{}'.format(self.animal_name, self.date)
        self.rec_path = os.path.join(self.data_path,
                            '{}/raw/{}/'.format(self.animal_name, self.date))
        self.copy_path = copy_path
        
        self.dio_id = dio_id

        self.placeholder_text = placeholder_text

        self.set_filename_format(filename_format=filename_format)
        self.task_code = task_code or {'r': 'run', 's': 'sleep'}
        self._detect_tasks()

        self.header_file = self._get_header_file(reconfig=reconfig)
        self._get_ntrodes_config()

        self.set_basic_info(experimenter_name=experimenter_name,
                            experiment_description=experiment_description,
                            session_description=session_description,
                            **subject_info)

    def set_filename_format(self, filename_format=None):
        '''
        Trode file name format
        =======================
        basic regular expression to match file (python re format):
          ^(\d*)_([a-zA-Z0-9]*)_(\d*)_{0,1}(\w*)\.{0,1}(.*)\.([a-zA-Z0-9]*)$

        6 groups:
        - date: although reg ex only matches digits,
                the date should be of format %YYYY%MM%DD
        - animal name: alphanumeric
        - epoch: digits (every epoch 2 digits ##,
                    multiple epochs in a file by series to digit pairs 010203)
        - label: alphanumeric (optional)
        - continuation extension: anything (recommend separator as period '.'
                but can be any whitespace non-alphanumeric.
                If separator is period, it is excluded from the match,
                if it is anything else it is included in the match.
                For camera/position data used to signify file continuation
                e.g. 01, 02, 03....)
        - file extension: alphanumeric (e.g. rec, stateScript, h264)
        '''
        if filename_format is None:
            # should fix!!!
            filename_format = '{date}_{animal}_{epoch}_{label}.{extension}'
            # filename_format = '{date}_{animal}_{epoch}_{session}(.{file})?.{extension}'

        format_keys, format_string = self.detect_filename_format(filename_format)
        self.filename_format = filename_format
        self.filename_format_keys = format_keys
        self.filename_format_string = format_string

    def get_filename(self, epoch, label, extension):
        if extension[0] == '.':
            extension = extension[1:]
            
        # should fix using the official regex format
        filename = '{date}_{animal}_{epoch}_{label}.{extension}'.format(
            date = self.date,
            animal = self.animal_name,
            epoch = epoch,
            label = label,
            extension = extension
        )
        return filename

    def _get_header_file(self, reconfig=None):
        ''' reconfig: path to reconfig file '''
        if (reconfig is not None) and Path(reconfig).is_file():
            # use provided reconfig file
            return reconfig
        else:
            # read from rec_header.xml files
            # (these files are generated during rec_to_nwb preprocessing)
            header_files = self.find_files_with_extension('.rec_header.xml')
            if len(header_files) == 0:
                # extract rec headers into a temporary directory
                self.extract_rec_headers()
                header_files = self.find_files_with_extension('.rec_header.xml',
                                                              path=self.copy_path)
            # just use the first header?
            return header_files[0]

    def extract_rec_headers(self):
        ''' creates .rec_header.xml (trodesconfig) files '''
        rec_files_list = self.find_files_with_extension('.rec')
        print('extracting {} rec header files into {}...'.format(
            len(rec_files_list), self.copy_path))
        for rec_file in rec_files_list:
            copy_rec_header(rec_file, copy_dir=self.copy_path)
        print('done.')

    def _detect_tasks(self):
        # get a dict with list values
        parsed = self.scan_file_components(unique=False)

        # get a sorted list of (epoch, label_task, label_num) tuples
        self.epoch_label_tuples = sorted(list(set(
            [(epoch, *self._parse_label(label))
                for epoch, label
                in zip(parsed['epoch'], parsed['label'])]
            )))

        # self.detected_tasks = list(set([t[1] for t in self.epoch_label_tuples]))
        # conserve epoch order
        detected_tasks = []
        for t in self.epoch_label_tuples:
            if t[1] in detected_tasks:
                continue
            detected_tasks.append(t[1])
        self.detected_tasks = detected_tasks

    def set_basic_info(self, experimenter_name=None,
                             experiment_description=None,
                             session_description=None,
                             **subject_info):
        # default template
        experiment_description = experiment_description or self.placeholder_text
        basic_info = {
            'experimenter name': experimenter_name or self.placeholder_text,
            'lab': 'Loren Frank',
            'institution': 'University of California, San Francisco',
            'experiment description': experiment_description,
            'session description': session_description or experiment_description,
            'session_id': self.session_id,
            'subject': {
                'description': subject_info.get('description', 'Long Evans Rat'),
                'genotype': subject_info.get('genotype', 'Wild Type'),
                'sex': subject_info.get('sex', 'Male'),
                'species': subject_info.get('species', 'Rat'),
                'subject id': self.animal_name,
                'weight': subject_info.get('weight', self.placeholder_text)
            }
        }
        self.basic_info = basic_info

    def get_config_from_header(self, reconfig=None):
        xml_data = read_xml(self.header_file)
        return xml_data['Configuration']

    def write_metadata_draft(self, out_path='yaml/'):
        ''' write section by section, to insert comments '''
        
        os.makedirs(out_path, exist_ok=True)
        
        # write (or overwrite) to this file
        out_filename = self.session_id + '_metadata_draft.yml'
        out_file = os.path.join(out_path, out_filename)

        # header
        meta_header = [
            out_filename,
            'This is a draft metadata file auto-generated by NWBMetadataHelper.',
            'This file still needs human attention -- double check all entries!',
            'In particular, search for the placeholder string \"{}\"'.format(self.placeholder_text),
            'and replace with appropriate values.'
            ''
            ]
        self._write_comments(out_file, meta_header, reset=True)

        # basic info section
        self._write_comments(out_file, ['', '', '=== basic information ==='])
        # self._write_comments(out_file, ['', 'double check!'])
        self._write_comments(out_file, [''])
        append_yml(out_file, self.basic_info)

        # then collect other fields
        self._write_comments(out_file, ['', '', '=== environment ==='])
        self._write_wrapper(out_file, self.get_data_acq_device)
        self._write_wrapper(out_file, self.get_associated_files)
        self._write_wrapper(out_file, self.get_device)
        self._write_wrapper(out_file, self.get_units)
        self._write_wrapper(out_file, self.get_conversion)
        self._write_wrapper(out_file, self.get_default_header_file_path)

        self._write_comments(out_file, ['', '', '=== behavior / video ==='])
        self._write_wrapper(out_file, self.get_cameras)
        self._write_wrapper(out_file, self.get_tasks)
        self._write_wrapper(out_file, self.get_associated_video_files)
        self._write_wrapper(out_file, self.get_behavioral_events)

        self._write_comments(out_file, ['', '', '=== electrodes ==='])
        self._write_wrapper(out_file, self.get_electrode_groups)
        self._write_comments(out_file, ['']) # extra spacing
        self._write_wrapper(out_file, self.get_ntrode_electrode_groups_channel_map)

        # last newline
        self._write_comments(out_file, [''])

        print('Saved to file:')
        print(out_file)


    def _write_wrapper(self, out_file, func):
        ''' getaround to write comments '''
        # prepare contents
        metadata, comments = func()

        # first write comments for the section
        spacing = ['', ''] # some spacing between sections
        if isinstance(comments, list):
            comments = spacing + comments
        else:
            comments = spacing
        self._write_comments(out_file, comments)

        # then append YAML-formatted metadata
        append_yml(out_file, metadata)

    @staticmethod
    def _write_comments(file, comments, reset=False, marker='#'):
        ''' file is a normal text file;
        comments is just a list of strings
        '''
        access_mode = 'a' # by default append
        if reset:
            access_mode = 'w'
        with io.open(file, access_mode) as fh:
            try:
                for line in comments:
                    if len(line.strip()) > 0 and line[0] != marker:
                        line = '# ' + line
                    fh.write(line + '\n')
            except Exception as e: # catch *all* exceptions
                print(e)


    def get_default_header_file_path(self):
        entry_key = 'default_header_file_path'
        comments = [
            # this is for header validation and can be left as is (below)
            # (something we can change in the future)
        ]
        meta_entry = 'default_header.xml'
        return {entry_key: meta_entry}, comments

    def get_data_acq_device(self):
        entry_key = 'data acq device'
        comments = [
            # can consider this fixed
        ]

        
        meta_entry = [
            {
            'name': 'SpikeGadgets',
            'amplifier': 'Intan',
            'adc_circuit': 'Intan'
            }
        ]
        return {entry_key: meta_entry}, comments

    def get_associated_files(self):
        entry_key = 'associated_files'
        comments = []

        raw_files = self.find_files_with_extension('.stateScriptLog')
        meta_entry = []
        for file in raw_files:
            parsed = self.parse_filename(file)
            ext = parsed['extension']
            label = parsed['label']
            out = {
                'name': '{}_{}'.format(ext, label),
                'description': '{} {}'.format(ext, self.unpack_label(label)),
                'path': str(file),
                'task_epochs': [int(parsed['epoch'])]
            }
            meta_entry.append(out)
        return {entry_key: meta_entry}, comments

    def get_device(self):
        entry_key = 'device'
        comments = [
            # can consider this fixed for all electrode-based experiments
            # probably no longer necessary
        ]

        meta_entry = {'name': ['Trodes']}
        return {entry_key: meta_entry}, comments

    def get_units(self):
        entry_key = 'units'
        comments = [
            # 'need input'
        ]

        meta_entry = {
            'analog': self.placeholder_text,
            'behavioral_events': self.placeholder_text
        }
        return {entry_key: meta_entry}, comments

    def get_conversion(self):
        comments = [
            # 'conversion factors:',
            'A/D units to volts: 0.195 uV / lsb' # determined by SpikesGadget
        ]
        entries = {
            'raw_data_to_volts': 0.000000195,
            # 'times_period_multiplier': self.placeholder_text # optional
        }
        return entries, comments

    def get_cameras(self):
        entry_key = 'cameras'
        comments = [
            # You can make the first (sleep) camera id:0 and the second (run) camera id:1.
            # We typically have two cameras, one for run and one for sleep.
            'meters_per_pixel: to be determined from video & maze dimensions'
        ]

        # placeholder for now (just match number of tasks)
        meta_entry = []
        for i, task in enumerate(self.detected_tasks):
            task_name = self.task_code.get(task, self.placeholder_text)
            out = {
                'id': i,
                'meters_per_pixel': self.placeholder_text,
                'manufacturer': self.placeholder_text,
                'model': self.placeholder_text,
                'lens': self.placeholder_text,
                'camera_name': '{} camera'.format(task_name)
            }
            meta_entry.append(out)
        return {entry_key: meta_entry}, comments

    def get_tasks(self):
        entry_key = 'tasks'
        comments = [
            # 'need manual input'
        ]

        # placeholder for now
        meta_entry = []
        for i, task in enumerate(self.detected_tasks):
            task_epochs = [int(t[0]) for t in self.epoch_label_tuples
                            if t[1] == task]
            task_name = self.task_code.get(task, self.placeholder_text)
            out = {
                'task_name': task_name,
                'task_description': task_name,
                'camera_id': [i],
                'task_epochs': task_epochs
            }
            meta_entry.append(out)
        return {entry_key: meta_entry}, comments

    def get_associated_video_files(self):
        entry_key = 'associated_video_files'
        comments = [
            'need camera information'
        ]

        raw_files = self.find_files_with_extension('.*h264')
        meta_entry = []
        for file in raw_files:
            parsed = self.parse_filename(file)
            basename = os.path.basename(file)
            t = self._parse_label(parsed['label'])[0] # 's' or 'r'
            camera_id = self.placeholder_text
            for i, task in enumerate(self.detected_tasks):
                if t == task:
                    camera_id = i
                    break
            out = {
                'name': basename,
                'camera_id': camera_id,
                'task_epochs': int(parsed['epoch'])
            }
            meta_entry.append(out)
        return {entry_key: meta_entry}, comments

    def get_behavioral_events(self):
        entry_key = 'behavioral_events'
        comments = [
            'read from dio_id (experimenter input)'
        ]

        xml_data = self.get_config_from_header()
        meta_entry = []
        for key in self.dio_id:
            for n, v in self.dio_id[key].items():
                out = {
                    'description': '{}{}'.format(key, n+1), # 1-based
                    'name': v
                }
                meta_entry.append(out)
        return {entry_key: meta_entry}, comments

    def _get_ntrodes_config(self):
        xml_data = self.get_config_from_header()
        ntrodes_config = self.extract_ntrodes_info(xml_data)
        
        electrode_groups = []
        group_id = 0
        ch_cnt = 0
        for ntrode in ntrodes_config:
            try:
                num_channels = sum([1 for k in ntrode['map']])
            except KeyError:
                continue
            if num_channels <= 4:
                group = {'id': group_id, 'device_type': 'tetrode_12.5.yml'}
                electrode_groups.append(group)
                ntrode['electrode_group'] = group_id
                group_id += 1
            elif num_channels <= 16:
                # this is a part of a 32-channel probe
                # in general this should be more flexible
                if ch_cnt + num_channels > 32:
                    # assign to a new electrode group
                    group_id += 1
                    ch_cnt = num_channels
                else:
                    ch_cnt += num_channels
                group = {'id': group_id, 'device_type': '32c-2s8mm6cm-20um-40um-dl.yml'}
                ntrode['electrode_group'] = group_id
            else:
                raise RuntimeError('unknown shank type')
                
        self.ntrodes_config = ntrodes_config
        self.electrode_groups = electrode_groups

    def get_electrode_groups(self):
        entry_key = 'electrode groups'
        comments = [
            'where is electrode groups information stored?'
        ]

        meta_entry = []
        for group in self.electrode_groups:
            out = {
                'id': group['id'],
                'location': self.placeholder_text,
                'device_type': group['device_type'],
                'targeted_location': self.placeholder_text,
                'targeted_x': self.placeholder_text,
                'targeted_y': self.placeholder_text,
                'targeted_z': self.placeholder_text,
                'units': self.placeholder_text
            }
            meta_entry.append(group)
        return {entry_key: meta_entry}, comments

    def get_ntrode_electrode_groups_channel_map(self):
        entry_key = 'ntrode electrode group channel map'
        comments = [
            'ntrode electrode group channel map:',
            'read directly from the header (or reconfig) xml file.',
            'need more work!!',
            ''
        ]

        meta_entry = self.ntrodes_config
        return {entry_key: meta_entry}, comments


    # ---------------

    @staticmethod
    def extract_ntrodes_info(config_all):
        ''' should check '''
        ntrode_config = config_all['SpikeConfiguration']['SpikeNTrode']
        ntrodes_info = []
        for ntrode in ntrode_config:
            nt = dict(ntrode_id=int(ntrode['id']),
                      electrode_group='Unknown',
                      bad_channels='Unknown')
            try:
                hwChan_map = {}
                for i, channel in enumerate(ntrode['SpikeChannel']):
                    hwChan_map[i] = int(channel['hwChan'])
                nt['map'] = hwChan_map
            except KeyError:
                print(' * WARNING: incomplete ntrode id {}'.format(ntrode['id']))
            ntrodes_info.append(nt)
        return ntrodes_info

    def find_files_with_extension(self, extension, path=None, sort_list=True):
        '''
        extension: a string like '.rec'
        returns a list of POSIXPATH objects '''
        path = path or self.rec_path
        if extension[0] != '.':
            extension = '.' + extension
        files = []
        for file_path in Path(path).glob('**/*' + extension):
            files.append(file_path)
        if sort_list:
            return sorted(files)
        return files

    def unpack_label(self, label, separator=' '):
        for k in self.task_code:
            if k in label:
                return label.replace(k, self.task_code[k] + separator)
        # if not found
        return label

    def _parse_label(self, label):
        ''' parse label 'r1' into a task code 'r' and a number '1' '''
        for k in self.task_code:
            if k in label:
                return k, label.replace(k, '')
        # if not found
        return label, ''

    def scan_file_components(self, unique=True):
        parsed_list = []
        for file_path in Path(self.rec_path).glob(
                    '**/{}_{}_*.*'.format(self.date, self.animal_nickname)
                    ):
            parsed = self.parse_filename(file_path)
            parsed_list.append(parsed)
        out = {}
        for k in self.filename_format_keys:
            v = [p[k] for p in parsed_list]
            if unique:
                v = list(set(v))
            out[k] = v

        # format check
        if unique:
            if out['date'] != [self.date]:
                print('something wrong: date mismatch')
            if (out['animal'] != [self.animal_name]) and (out['animal'] != [self.animal_nickname]):
                print('something wrong: animal name mismatch')
        return out

    def parse_filename(self, file_path):
        basename = os.path.basename(file_path) # FILENAME.ext
        parsed_list = parse.parse(self.filename_format_string, basename)
        parsed = {}
        for k, v in zip(self.filename_format_keys, parsed_list):
            parsed[k] = v
        return parsed

    @staticmethod
    def detect_filename_format(format_input):
        format_keys = re.findall(r"\{(\w+)\}", format_input)
        format_string = re.sub('\{(\w+)\}', '{}', format_input)
        return format_keys, format_string
