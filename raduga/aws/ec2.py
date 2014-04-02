from time import sleep

class AWSEC2(object):
    def __init__(self, target):
        self.conn = target.get_ec2_conn()

    def get_instance_state(self, instance_id):
        instance = self.conn.get_only_instances(instance_id)[0]
        return instance.state

    def stop_instance(self, instance_id):
        self.conn.stop_instances(instance_id)

    def create_ami(self, instance_id, name, description, tags):
        instance = self.conn.get_only_instances(instance_id)[0]
        if instance.state != 'stopped':
            raise RuntimeError("Won't create AMI from non-stopped instance")
        image_id = self.conn.create_image(instance_id, name, description)
        sleep(1)
        # Add tags to the image
        self.conn.create_tags(image_id, tags)
        return image_id

    def get_ami_state(self, image_id):
        ami = self.conn.get_all_images(image_id)[0]
        return ami.state

    def find_ami(self, **tags):
        filters = dict(map(lambda (k,v): ("tag:"+k,v), tags.items()))
        results = self.conn.get_all_images(owners=['self'], filters=filters)
        if len(results) == 0:
            return None
        elif len(results) == 1:
            return results[0].id
        else:
            raise RuntimeError("More than ona AMI is matching the requested tags (??!)")
