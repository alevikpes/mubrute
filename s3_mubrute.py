#!/usr/bin/env python 
import requests 
import argparse
import time, sys, subprocess, shlex, os, warnings
import re, json

warnings.filterwarnings("ignore")
banner = '''                  __                      
                 |  |                     ___
 ________ ___ ___|  |___ _____ ___ ___ __|   |__ ______    
|        |   |   |      |   __|   |   |         |      |
|  |  |  |   |   |  | | |  |  |   |   |--|   |--| |____|
|__|__|__|_______|______|__|  |_______|  |___|  |______|
'''

#set global vars
agent = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/57.0.2987.133 Safari/537.36'}
mutators = [] #strings to mutate input
mutations = [] #mutated strings for enumeration
regions = ['us-east-2', 'us-east-1', 'us-west-1', 'us-west-2', 'ca-central-1', 'ap-south-1', 'ap-northeast-2', 'ap-southeast-1', 'ap-southeast-2', 
'ap-northeast-1', 'eu-central-1', 'eu-west-1', 'eu-west-2', 'sa-east-1'] #all S3 regions
epoch = str(int(time.time()))
cwd = os.getcwd()

#Strings for Bash coloring; format = colors.color+string+color.CLOSE
class colors:
    PURPLE = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CLOSE = '\033[0m'
    BOLD = '\033[1m'

def mutate(target):
    #mutates string then writes to list; performs basic mutations of string and of substrings
    half = target[:int((len(target)/2))]
    mutations.append(target)
    mutations.append(half)

    for each in mutators:
        mutations.append(each+target)
        mutations.append(target+each)
        mutations.append(half+target)
        mutations.append(each+half)
        
        mutations.append(each+'-'+target)
        mutations.append(each+'-'+half)
        mutations.append(each+'.'+target)
        mutations.append(each+'.'+half) 

        mutations.append(target+'-'+each)
        mutations.append(half+'-'+each)
        mutations.append(target+'.'+each)
        mutations.append(half+'.'+each)

def readin(filen,op):
    #in operation is used for default mutators list
    #out operation is used for reading in a premade wordlist
    with open(filen,'r') as mus:
        if op == 'out':
            for line in mus:
                mutations.append(line.strip())
        elif op == 'in':
            for line in mus:
                mutators.append(line.strip())
        else:
            print colors.RED+'[-] Error...quitting!'+colors.CLOSE
            sys.exit()

def nslookup(domain):
    #get the IP of the S3 bucket
    proc1 = subprocess.check_output(["nslookup",domain])
    addrlist = re.findall('Address:.*?\n', proc1, re.DOTALL)
    addr = (addrlist[-1])[9:].strip()

    #nslookup the IP --> 
    #if it contains a region from the master list, return the region // otherwise, return the an error
    proc2 = subprocess.check_output(["nslookup", addr])
    region = None
    for reg in regions:
        if reg in proc2: 
            region = reg
    if region is not None:
        return colors.CLOSE+region+colors.CLOSE
    else:
        return colors.RED+'Cannot determine region'+colors.CLOSE

def getacl(bucket):
    #call the AWS CLI to get the bucket's ACL
    #Shlex will tokenize the command string properly for subprocess
    cmd =  'aws s3api get-bucket-acl --bucket '+bucket+' --query \'Grants[].{Permission: Permission, URI: Grantee.URI, ID: Grantee.ID, User: Grantee.DisplayName }\' --no-sign-request'
    tokenized = shlex.split(cmd)

    #handles access denied errors from the CLI
    try:
        proc = subprocess.check_output(tokenized, stderr=open(os.devnull, 'w'))
    except:
        return [colors.RED+'No anonymous access'+colors.CLOSE]
    dic = json.loads(proc)

    retdic = []
    #Check what anonymous users can do with the bucket
    if any(item['Permission'] == 'WRITE' and item['URI'] == 'http://acs.amazonaws.com/groups/global/AllUsers' for item in dic):
        retdic.append(colors.GREEN+'Objects world writeable!'+colors.CLOSE)
    if any(item['Permission'] == 'WRITE_ACP' and item['URI'] == 'http://acs.amazonaws.com/groups/global/AllUsers' for item in dic):
        retdic.append(colors.GREEN+'ACL world writeable!'+colors.CLOSE)
    if any(item['Permission'] == 'FULL_CONTROL' and item['URI'] == 'http://acs.amazonaws.com/groups/global/AllUsers' for item in dic):
        retdic.append(colors.GREEN+'Full anonymous control!'+colors.CLOSE)
    
    return retdic

def switch(mutations):
    i = 1
    for mu in mutations:
        url = 'http://'+mu+'.s3.amazonaws.com'
        try:
            r = requests.get(url, headers=agent, allow_redirects=True, verify=False)
            
            if args['suppress'] == True:
                if r.status_code == 200 or r.status_code == 403:
                    print '['+str(i)+'/'+str(len(mutations))+']',
            else:
                print '['+str(i)+'/'+str(len(mutations))+']',
            
            if r.status_code == 200:   #200 = bucket exists and you can call ListObjects() unauthenticated (equivalent to 'aws s3 ls s3://bucket --no-sign-request')
                print colors.GREEN+'200'+colors.CLOSE+' - '+url
                print '                Region - '+nslookup(mu+'.s3.amazonaws.com')
                for aclpol in getacl(mu):
                    print '                '+aclpol
                print colors.BLUE+'                Saving files in contents directory'+colors.CLOSE
                parse(mu, r.text)
            elif r.status_code == 403: #403 = bucket exists but you cannot list contents
                print colors.YELLOW+'403'+colors.CLOSE+' - '+url
                print '                Region: '+nslookup(mu+'.s3.amazonaws.com')
                for aclpol in getacl(mu):
                    print '                '+aclpol
            elif r.status_code == 404 and args['suppress'] != True: 
                print colors.RED+'404'+colors.CLOSE+' - '+url
            elif args['suppress'] != True:                      
                print colors.PURPLE+r.status_code+colors.CLOSE+' - '+url
        except Exception: #this condition will be triggered by requesting a bucket that breaks the naming policy
            print colors.RED+'Error requesting '+url+colors.CLOSE
        i += 1
 
def parse(mu, resp):
#parse through the XML response with RegEx (because its easier than using etree)
    writeto = open(cwd+'/contents_'+epoch+'/'+mu+'.txt', 'w+')
    for each in re.findall('<Key>.*?</Key>', resp, re.DOTALL):
        url = 'http://'+mu+'.s3.amazonaws.com/'+(each[5:len(each)-6]).strip() #strip the attributes and newlines
        if url[len(url)-1:len(url)] != '/':                                   #filtering out directories
            writeto.write((url+'\n').encode('utf-8'))
    writeto.close()
   
#Customized help menu for argparser
def helpmsg(name=None):
    return banner+'\n'+'''AWS S3 Bucket Enumerator
./s3_mubrute.py [-t <target>] [-f <file.ext>] [-s, --suppress]

Usage:
   Use built-in mutator:   ./s3_mubrute.py -t string
   Use pre-made wordlist:  ./s3_mubrute.py -f list.txt

Options:
   -t              target string
                   usable chars: [aA-zZ], [0-9], '.' and '-' (see README)
   -f              input wordlist
   -s, --suppress  only print buckets that exist in the output
   -h, --help      print this help menu
'''

#checks if input file exists; if not, quit
def filehandler(f):
    if not os.path.isfile(f):
        print colors.RED+'[-] Input file does not exist...quitting!'+colors.CLOSE
        sys.exit()
    else:
        readin(f, 'out')

parser = argparse.ArgumentParser(usage=helpmsg(), add_help=False)                             #suppress normally generated help menu
parser.add_argument('-h', '--help', dest='helpbool', action='store_true', required=False)
parser.add_argument('-t', dest='target', type=str, required=False)
parser.add_argument('-f', required=False, type=lambda f: filehandler(f))                      #check if file exists
parser.add_argument('-s', '--suppress', dest='suppress', action='store_true', required=False)
args = vars(parser.parse_args())

#print help then quit if no arguments are supplied or if -h provided
if len(sys.argv) == 1 or args['helpbool'] == True:
	print helpmsg()
	sys.exit()  

#main
try:
    #ascii art is required ;)
    print banner
    os.makedirs(cwd+'/contents_'+epoch)

    #check if mutations are empty (no user supplied list)
    #if empty, use default mutation list against the target
    if len(mutations) == 0:
        readin('mutators.txt', 'in')
        if args['target'] is not None:
            mutate(args['target'])
        else:
            print colors.RED+'[-] Target missing...quitting!'+colors.CLOSE

    #remove duplicates then enumerate based on status code
    mutations = set(mutations)
    print colors.BLUE+'[+]   Printing results'+colors.CLOSE

    switch(mutations)
    print '[+]   Contents directory: '+colors.BOLD+'/contents_'+epoch+'/'+colors.CLOSE
except KeyboardInterrupt:
    print '\n[-]   Quitting early. Incomplete results written to: '+colors.BOLD+'/contents_'+epoch+'/'+colors.CLOSE
    sys.exit()